"""Wallet address export: the ground truth the analysis attributes outputs with."""

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer

ENTRYPOINT = (
    Path(__file__).resolve().parents[1]
    / "containers"
    / "joinmarket-client-server"
    / "jmwalletd_entrypoint.py"
)


def load_entrypoint() -> ModuleType:
    spec = importlib.util.spec_from_file_location("jmwalletd_entrypoint", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_the_wallet_daemon_is_patched_to_display_every_address() -> None:
    entrypoint = load_entrypoint()
    calls = []

    def wallet_display(wallet_service, showprivkey, displayall=False):
        calls.append(displayall)
        return {}

    module = SimpleNamespace(wallet_display=wallet_display)

    assert entrypoint.install_display_all_addresses(module) is True
    module.wallet_display(object(), False)

    assert calls == [True]
    assert entrypoint.install_display_all_addresses(module) is False
