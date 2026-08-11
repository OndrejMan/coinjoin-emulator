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


def main() -> int:
    enabled = os.getenv("JM_DESCRIPTOR_REGTEST_FALLBACK", "0").strip().lower() in TRUE_VALUES
    if enabled:
        install_descriptor_regtest_fallback()
    sys.argv = [JMWALLETD_PATH, *sys.argv[1:]]
    runpy.run_path(JMWALLETD_PATH, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
