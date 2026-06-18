import unittest
from unittest.mock import patch

from joinmarket_helpers import response

from manager.wasabi_clients.joinmarket_client import JoinMarketClientServer


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

    def test_get_balance_converts_wallet_available_balance_to_sats(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch.object(
            client,
            "display_wallet",
            return_value={"walletinfo": {"available_balance": "1.25000000"}},
        ):
            self.assertEqual(client.get_balance(), 125_000_000)
