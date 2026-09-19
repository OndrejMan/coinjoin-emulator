"""Wallet address export: the ground truth the analysis attributes outputs with."""

from unittest.mock import Mock

from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer


def test_every_derived_address_is_exported_not_only_unspent_ones() -> None:
    client = object.__new__(JoinMarketClientServer)
    client.seedphrase = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    client.display_wallet = Mock(
        return_value={
            "walletinfo": {
                "accounts": [
                    {
                        "account": "0",
                        "branches": [
                            {
                                "entries": [
                                    {
                                        "address": "bcrt1qspent",
                                        "hd_path": "m/84'/1'/0'/0/7",
                                        "status": "used",
                                        "amount": "0.00000000",
                                    },
                                    {
                                        "address": "bcrt1qnew",
                                        "hd_path": "m/84'/1'/0'/1/7",
                                        "status": "new",
                                        "amount": "0.00000000",
                                    },
                                ]
                            }
                        ],
                    }
                ]
            }
        }
    )

    keys = client.list_keys()

    assert [key["address"] for key in keys] == ["bcrt1qspent", "bcrt1qnew"]
    assert keys[0] == {
        "full_key_path": "m/84'/1'/0'/0/7",
        "pubKey": (
            "04105d0e55b9a741b873a9c0bd52ecac6f85f58de93e19d48c8c0ea33f54806b"
            "5f407981e763e5f1c139a38790df9e6d62e9fe3cfcae3cba4c4b157616dab7e118"
        ),
        "internal": False,
        "address": "bcrt1qspent",
        "path": "m/84'/1'/0'/0/7",
        "account": "0",
        "status": "used",
        "amount": "0.00000000",
    }
    assert keys[1]["internal"] is True
    client.display_wallet.assert_called_once_with(display_all=True)


def test_non_bip32_address_is_kept_without_key_metadata() -> None:
    client = object.__new__(JoinMarketClientServer)
    client.seedphrase = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    client.display_wallet = Mock(
        return_value={
            "walletinfo": {
                "accounts": [
                    {
                        "account": "fidelity-bonds",
                        "branches": [
                            {
                                "entries": [
                                    {
                                        "address": "bcrt1qbond",
                                        "hd_path": "79:1785542400",
                                        "status": "used",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        }
    )

    assert client.list_keys() == [
        {
            "full_key_path": "79:1785542400",
            "pubKey": None,
            "internal": None,
            "address": "bcrt1qbond",
            "path": "79:1785542400",
            "account": "fidelity-bonds",
            "status": "used",
            "amount": "",
        }
    ]


def test_display_wallet_requests_the_upstream_displayall_option() -> None:
    client = object.__new__(JoinMarketClientServer)
    client.walletname = "wallet.jmdat"
    client._rpc = Mock(return_value={})  # pylint: disable=protected-access

    assert client.display_wallet(display_all=True) == {}
    client._rpc.assert_called_once_with(  # pylint: disable=protected-access
        "GET", "/wallet/wallet.jmdat/display?displayall=true"
    )
