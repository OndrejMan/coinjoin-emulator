import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

# pylint: disable=protected-access

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = (
    PROJECT_ROOT
    / "containers"
    / "joinmarket-client-server"
    / "jmwalletd_entrypoint.py"
)


def load_entrypoint() -> ModuleType:
    spec = importlib.util.spec_from_file_location("jmwalletd_entrypoint", ENTRYPOINT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RpcError(Exception):
    code = -4
    message = "This wallet has no available keys"


class JsonRpc:
    def __init__(self) -> None:
        self.url = "/wallet/jm_wallet"
        self.urls: list[str] = []

    def setURL(self, url: str) -> None:
        self.url = url
        self.urls.append(url)


class RegtestBitcoinCoreInterface:
    def __init__(self) -> None:
        self.jsonRpc = JsonRpc()
        self.calls: list[tuple[str, list[object], str]] = []

    def _rpc(self, method: str, params: list[object] | None = None) -> object:
        rpc_params = [] if params is None else params
        self.calls.append((method, rpc_params, self.jsonRpc.url))
        if method == "getnewaddress" and self.jsonRpc.url == "/wallet/jm_wallet":
            raise RpcError()
        if method == "listwallets":
            return ["wallet"]
        if method == "getnewaddress" and self.jsonRpc.url == "/wallet/wallet":
            return "funding-address"
        if method == "getmempoolinfo" and rpc_params == []:
            return {"mempoolminfee": 0.00001}
        raise AssertionError(f"unexpected RPC call: {method} {rpc_params}")


def test_descriptor_regtest_fallback_uses_funding_wallet_and_restores_url() -> None:
    entrypoint = load_entrypoint()
    blockchaininterface = SimpleNamespace(
        RegtestBitcoinCoreInterface=RegtestBitcoinCoreInterface
    )
    interface = RegtestBitcoinCoreInterface()

    installed = entrypoint.install_descriptor_regtest_fallback(blockchaininterface)
    address = interface._rpc("getnewaddress", [])

    assert installed
    assert address == "funding-address"
    assert interface.jsonRpc.url == "/wallet/jm_wallet"
    assert interface.jsonRpc.urls == ["", "/wallet/wallet", "/wallet/jm_wallet"]
    assert interface.calls == [
        ("getnewaddress", [], "/wallet/jm_wallet"),
        ("listwallets", [], ""),
        ("getnewaddress", [], "/wallet/wallet"),
    ]


def test_descriptor_regtest_fallback_preserves_optional_rpc_params() -> None:
    entrypoint = load_entrypoint()
    blockchaininterface = SimpleNamespace(
        RegtestBitcoinCoreInterface=RegtestBitcoinCoreInterface
    )
    interface = RegtestBitcoinCoreInterface()

    entrypoint.install_descriptor_regtest_fallback(blockchaininterface)
    mempool_info = interface._rpc("getmempoolinfo")

    assert mempool_info == {"mempoolminfee": 0.00001}
    assert interface.calls == [("getmempoolinfo", [], "/wallet/jm_wallet")]


def test_parse_args_defaults_descriptor_regtest_fallback_off(monkeypatch: pytest.MonkeyPatch) -> None:
    entrypoint = load_entrypoint()
    monkeypatch.delenv("JM_DESCRIPTOR_REGTEST_FALLBACK", raising=False)

    enabled, jmwalletd_args = entrypoint.parse_args(["--datadir=/tmp/jm"])

    assert not enabled
    assert jmwalletd_args == ["--datadir=/tmp/jm"]


def test_parse_args_can_enable_descriptor_regtest_fallback() -> None:
    entrypoint = load_entrypoint()

    enabled, jmwalletd_args = entrypoint.parse_args(
        ["--descriptor-regtest-fallback", "--datadir=/tmp/jm"]
    )

    assert enabled
    assert jmwalletd_args == ["--datadir=/tmp/jm"]


def test_parse_bool_rejects_unknown_values() -> None:
    entrypoint = load_entrypoint()

    with pytest.raises(ValueError):
        entrypoint.parse_bool("sometimes")


class WalletRpcModule:
    """Stands in for ``jmclient.wallet_rpc``, whose only relevant name is this one."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def wallet_display(*args: object, **kwargs: object) -> object:
            self.calls.append((args, kwargs))
            return {"walletinfo": {}}

        self.wallet_display = wallet_display


def test_display_all_addresses_forces_displayall_for_keyword_callers() -> None:
    module = load_entrypoint()
    wallet_rpc = WalletRpcModule()

    assert module.install_display_all_addresses(wallet_rpc) is True

    wallet_rpc.wallet_display(object(), False, jsonified=True)
    (args, kwargs) = wallet_rpc.calls[0]
    assert kwargs["displayall"] is True
    assert kwargs["jsonified"] is True
    assert len(args) == 2


def test_display_all_addresses_overrides_a_positional_displayall() -> None:
    module = load_entrypoint()
    wallet_rpc = WalletRpcModule()
    module.install_display_all_addresses(wallet_rpc)

    wallet_rpc.wallet_display(object(), False, False, True)
    (args, kwargs) = wallet_rpc.calls[0]
    # The caller's ``displayall=False`` is replaced; ``serialized=True`` survives.
    assert args[2] is True
    assert args[3] is True
    assert "displayall" not in kwargs


def test_display_all_addresses_is_installed_only_once() -> None:
    module = load_entrypoint()
    wallet_rpc = WalletRpcModule()

    assert module.install_display_all_addresses(wallet_rpc) is True
    patched = wallet_rpc.wallet_display
    assert module.install_display_all_addresses(wallet_rpc) is False
    assert wallet_rpc.wallet_display is patched
