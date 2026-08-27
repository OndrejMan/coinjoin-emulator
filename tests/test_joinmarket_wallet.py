import unittest
from unittest.mock import patch

import requests

from manager.exceptions import RpcError
from manager.wasabi_clients.joinmarket_client import JoinMarketClientServer
from tests.joinmarket_helpers import response

# pylint: disable=protected-access


class JoinMarketWalletTest(unittest.TestCase):
    def test_create_wallet_and_unlock_do_not_require_existing_token(self) -> None:
        client = JoinMarketClientServer(host="dind")
        create_response = response(body={"token": "created-token", "refresh_token": "created-refresh"})
        unlock_response = response(body={"token": "unlocked-token", "refresh_token": "unlocked-refresh"})

        with patch(
            "manager.wasabi_clients.joinmarket.rpc.requests.request",
            side_effect=[create_response, unlock_response],
        ) as request:
            client._create_wallet()
            client.unlock_wallet()

        self.assertEqual(request.call_args_list[0].kwargs["headers"], {})
        self.assertEqual(request.call_args_list[1].kwargs["headers"], {})
        self.assertEqual(client.token, "unlocked-token")
        self.assertEqual(client.refresh_token, "unlocked-refresh")

    def test_create_wallet_uses_long_single_attempt_timeout(self) -> None:
        client = JoinMarketClientServer(host="dind")
        create_response = response(body={"token": "created-token", "refresh_token": "created-refresh"})

        with patch(
            "manager.wasabi_clients.joinmarket.rpc.requests.request",
            return_value=create_response,
        ) as request:
            client._create_wallet()

        self.assertEqual(request.call_args.kwargs["timeout"], 60)

    def test_create_wallet_does_not_repeat_after_timeout(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch(
            "manager.wasabi_clients.joinmarket.rpc.requests.request",
            side_effect=requests.exceptions.Timeout,
        ) as request:
            with self.assertRaises(TimeoutError):
                client._create_wallet()

        self.assertEqual(request.call_count, 1)

    def test_get_balance_converts_wallet_available_balance_to_sats(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch.object(
            client,
            "display_wallet",
            return_value={"walletinfo": {"available_balance": "1.25000000"}},
        ):
            self.assertEqual(client.get_balance(), 125_000_000)

    def test_list_keys_flattens_every_derived_address(self) -> None:
        client = JoinMarketClientServer(host="dind")
        display = {
            "walletinfo": {
                "accounts": [
                    {
                        "account": "0",
                        "branches": [
                            {
                                "branch": "external addresses\tm/84'/1'/0'/0",
                                "entries": [
                                    {
                                        "hd_path": "m/84'/1'/0'/0/000",
                                        "address": "bcrt1qexternal",
                                        "amount": "0.00000000",
                                        "status": "used",
                                    }
                                ],
                            },
                            {
                                "branch": "internal addresses\tm/84'/1'/0'/1",
                                "entries": [
                                    {
                                        "hd_path": "m/84'/1'/0'/1/000",
                                        "address": "bcrt1qchange",
                                        "amount": "0.10000000",
                                        "status": "cj-out",
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "account": "1",
                        "branches": [
                            {
                                "entries": [
                                    {
                                        "hd_path": "m/84'/1'/1'/0/000",
                                        "address": "bcrt1qmixdepth1",
                                        "amount": "0.00000000",
                                        "status": "new",
                                    }
                                ]
                            }
                        ],
                    },
                ]
            }
        }

        with patch.object(client, "display_wallet", return_value=display):
            keys = client.list_keys()

        self.assertEqual(
            keys,
            [
                {
                    "address": "bcrt1qexternal",
                    "path": "m/84'/1'/0'/0/000",
                    "account": "0",
                    "status": "used",
                    "amount": "0.00000000",
                },
                {
                    "address": "bcrt1qchange",
                    "path": "m/84'/1'/0'/1/000",
                    "account": "0",
                    "status": "cj-out",
                    "amount": "0.10000000",
                },
                {
                    "address": "bcrt1qmixdepth1",
                    "path": "m/84'/1'/1'/0/000",
                    "account": "1",
                    "status": "new",
                    "amount": "0.00000000",
                },
            ],
        )

    def test_list_keys_skips_entries_without_an_address(self) -> None:
        client = JoinMarketClientServer(host="dind")
        display = {
            "walletinfo": {
                "accounts": [
                    {
                        "account": "0",
                        "branches": [
                            {"entries": [{"hd_path": "m/84'/1'/0'/0/000", "address": ""}]}
                        ],
                    }
                ]
            }
        }

        with patch.object(client, "display_wallet", return_value=display):
            self.assertEqual(client.list_keys(), [])

    def test_list_keys_tolerates_a_wallet_display_without_accounts(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch.object(client, "display_wallet", return_value={}):
            self.assertEqual(client.list_keys(), [])

    def test_wait_wallet_does_not_recreate_wallet_after_successful_create(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch.object(client, "_create_wallet") as create_wallet, \
            patch.object(client, "get_new_address", side_effect=[TimeoutError("timeout"), "bcrt1ready"]), \
            patch("manager.wasabi_clients.joinmarket.wallet.sleep"):
            self.assertTrue(client.wait_wallet(timeout=5))

        create_wallet.assert_called_once_with()

    def test_wait_wallet_retries_create_until_first_success(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch.object(
            client,
            "_create_wallet",
            side_effect=[TimeoutError("timeout"), {"token": "created"}],
        ) as create_wallet, \
            patch.object(client, "get_new_address", side_effect=[TimeoutError("timeout"), "bcrt1ready"]), \
            patch("manager.wasabi_clients.joinmarket.wallet.sleep"):
            self.assertTrue(client.wait_wallet(timeout=5))

        self.assertEqual(create_wallet.call_count, 2)

    def test_wait_wallet_accepts_already_unlocked_wallet_as_created(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch.object(
            client,
            "_create_wallet",
            side_effect=RpcError("Error 401: Wallet already unlocked."),
        ) as create_wallet, \
            patch.object(client, "get_new_address", return_value="bcrt1ready"), \
            patch("manager.wasabi_clients.joinmarket.wallet.sleep"):
            self.assertTrue(client.wait_wallet(timeout=5))

        create_wallet.assert_called_once_with()

    def test_wait_wallet_continues_after_no_wallet_loaded_readiness_error(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch.object(client, "_create_wallet", return_value={"token": "created"}) as create_wallet, \
            patch.object(
                client,
                "get_new_address",
                side_effect=[RpcError("Error 401: No wallet loaded."), "bcrt1ready"],
            ), \
            patch("manager.wasabi_clients.joinmarket.wallet.sleep"):
            self.assertTrue(client.wait_wallet(timeout=5))

        create_wallet.assert_called_once_with()
