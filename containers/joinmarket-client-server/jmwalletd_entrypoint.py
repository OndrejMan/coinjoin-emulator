#!/usr/bin/env python3
"""Start jmwalletd with an optional descriptor-regtest compatibility patch."""

import os
import runpy
import sys
from collections.abc import Collection
from typing import Callable, Protocol, cast

JMWALLETD_PATH = "/jm/clientserver/scripts/jmwalletd.py"
FUNDING_WALLET_RPC_PATH = "/wallet/wallet"
FUNDING_WALLET_NAME = "wallet"
TRUE_VALUES = {"1", "true", "yes", "on"}

RpcMethod = Callable[["RegtestBitcoinCoreInterface", str, list[object] | None], object]


class JsonRpc(Protocol):
    url: str

    def setURL(self, url: str) -> None: ...


class RegtestBitcoinCoreInterface(Protocol):
    jsonRpc: JsonRpc


class RegtestBitcoinCoreInterfaceType(Protocol):
    _rpc: RpcMethod


class BlockchainInterface(Protocol):
    RegtestBitcoinCoreInterface: RegtestBitcoinCoreInterfaceType


class WalletDisplay(Protocol):
    _display_all_addresses: bool

    def __call__(
        self,
        wallet_service: object,
        showprivkey: bool,
        *args: object,
        **kwargs: object,
    ) -> object: ...


class WalletRpcModule(Protocol):
    wallet_display: WalletDisplay


class PatchedRpcMethod(Protocol):
    _descriptor_regtest_fallback: bool

    def __call__(
        self,
        self_interface: RegtestBitcoinCoreInterface,
        method: str,
        params: list[object] | None = None,
    ) -> object: ...


def is_no_keys_getnewaddress(method: str, error: Exception) -> bool:
    return (
        method == "getnewaddress"
        and getattr(error, "code", None) == -4
        and "no available keys" in str(getattr(error, "message", error))
    )


def install_descriptor_regtest_fallback(
    blockchaininterface: BlockchainInterface | None = None,
) -> bool:
    if blockchaininterface is None:
        from jmclient import blockchaininterface as imported  # pylint: disable=import-error,import-outside-toplevel

        blockchaininterface = cast(BlockchainInterface, imported)

    interface_class = blockchaininterface.RegtestBitcoinCoreInterface
    original_rpc = interface_class._rpc  # pylint: disable=protected-access
    if getattr(original_rpc, "_descriptor_regtest_fallback", False):
        return False

    def rpc_with_fallback(
        self: RegtestBitcoinCoreInterface,
        method: str,
        params: list[object] | None = None,
    ) -> object:
        try:
            return original_rpc(self, method, params or [])
        except Exception as error:  # pylint: disable=broad-exception-caught
            if not is_no_keys_getnewaddress(method, error):
                raise
            original_url = self.jsonRpc.url
            try:
                self.jsonRpc.setURL("")
                loaded = cast(Collection[str], original_rpc(self, "listwallets", []))
                if FUNDING_WALLET_NAME not in loaded:
                    original_rpc(self, "loadwallet", [FUNDING_WALLET_NAME])
                self.jsonRpc.setURL(FUNDING_WALLET_RPC_PATH)
                return original_rpc(self, "getnewaddress", [])
            finally:
                self.jsonRpc.setURL(original_url)

    patched = cast(PatchedRpcMethod, rpc_with_fallback)
    patched._descriptor_regtest_fallback = True  # pylint: disable=protected-access
    interface_class._rpc = patched  # pylint: disable=protected-access
    return True


def install_display_all_addresses(
    wallet_rpc: WalletRpcModule | None = None,
) -> bool:
    """Make the wallet display include every derived address, including spent ones."""
    if wallet_rpc is None:
        from jmclient import wallet_rpc as imported_wallet_rpc  # pylint: disable=import-error,import-outside-toplevel

        wallet_rpc = cast(WalletRpcModule, imported_wallet_rpc)

    original_display = wallet_rpc.wallet_display
    if getattr(original_display, "_display_all_addresses", False):
        return False

    def wallet_display_all(
        wallet_service: object,
        showprivkey: bool,
        *args: object,
        **kwargs: object,
    ) -> object:
        if args:
            args = (True, *args[1:])
        else:
            kwargs["displayall"] = True
        return original_display(wallet_service, showprivkey, *args, **kwargs)

    patched_display = cast(WalletDisplay, wallet_display_all)
    patched_display._display_all_addresses = True  # pylint: disable=protected-access
    wallet_rpc.wallet_display = patched_display
    return True


def main() -> int:
    enabled = os.getenv("JM_DESCRIPTOR_REGTEST_FALLBACK", "0").strip().lower() in TRUE_VALUES
    if enabled:
        install_descriptor_regtest_fallback()
    install_display_all_addresses()
    sys.argv = [JMWALLETD_PATH, *sys.argv[1:]]
    runpy.run_path(JMWALLETD_PATH, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
