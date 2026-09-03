import importlib.util
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "containers" / "joinmarket-client-server" / "jmwalletd_entrypoint.py"


def load_entrypoint() -> ModuleType:
    spec = importlib.util.spec_from_file_location("jmwalletd_entrypoint", ENTRYPOINT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WalletRpcModule:
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
    args, kwargs = wallet_rpc.calls[0]
    assert kwargs["displayall"] is True
    assert kwargs["jsonified"] is True
    assert len(args) == 2


def test_display_all_addresses_overrides_a_positional_displayall() -> None:
    module = load_entrypoint()
    wallet_rpc = WalletRpcModule()
    module.install_display_all_addresses(wallet_rpc)

    wallet_rpc.wallet_display(object(), False, False, True)
    args, kwargs = wallet_rpc.calls[0]
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
