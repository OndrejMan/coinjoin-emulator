"""Wallet address export: the ground truth the analysis attributes outputs with."""

from unittest.mock import Mock

from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer


def test_every_derived_address_is_exported_not_only_unspent_ones() -> None:
    client = object.__new__(JoinMarketClientServer)
    client.display_wallet = Mock(
        return_value={
            "walletinfo": {
                "accounts": [
                    {
                        "account": "0",
                        "branches": [
                            {
                                "entries": [
                                    {"address": "bcrt1qspent", "hd_path": "m/0/0", "status": "used"},
                                    {"address": "bcrt1qnew", "hd_path": "m/0/1", "status": "new"},
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
    assert keys[0]["path"] == "m/0/0"
    client.display_wallet.assert_called_once_with(display_all=True)


def test_display_wallet_requests_the_upstream_displayall_option() -> None:
    client = object.__new__(JoinMarketClientServer)
    client.walletname = "wallet.jmdat"
    client._rpc = Mock(return_value={})  # pylint: disable=protected-access

    assert client.display_wallet(display_all=True) == {}
    client._rpc.assert_called_once_with(  # pylint: disable=protected-access
        "GET", "/wallet/wallet.jmdat/display?displayall=true"
    )
