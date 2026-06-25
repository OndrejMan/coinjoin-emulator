#!/usr/bin/env python3
import argparse
import os
import runpy
import sys
from collections.abc import Collection
from datetime import datetime
from typing import Callable, Protocol, cast
from zoneinfo import ZoneInfo

JMWALLETD_PATH = "/jm/clientserver/scripts/jmwalletd.py"
FUNDING_WALLET_RPC_PATH = "/wallet/wallet"
FUNDING_WALLET_NAME = "wallet"

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
PRAGUE_TZ = ZoneInfo("Europe/Prague")
RESET_COLOR = "\033[0m"
INFO_COLOR = "\033[36m"

RpcMethod = Callable[["RegtestBitcoinCoreInterface", str, list[object] | None], object]


def log_info(message: object) -> None:
    timestamp = datetime.now(PRAGUE_TZ).strftime("%H:%M:%S")
    prefix = f"INFO | {timestamp} |"
    color_mode = os.getenv("COINJOIN_LOG_COLOR", "auto").lower()
    use_color = color_mode in {"1", "true", "always", "yes"} or (
        color_mode not in {"0", "false", "never", "no"}
        and not os.getenv("NO_COLOR")
        and sys.stdout.isatty()
    )
    if use_color:
        prefix = f"{INFO_COLOR}{prefix}{RESET_COLOR}"
    sys.stdout.write(f"{prefix} {message}\n")


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


def parse_bool(value: str | None, default: bool = True) -> bool:
    if value is None or value == "":
        return default

    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(
        "expected one of "
        f"{sorted(TRUE_VALUES | FALSE_VALUES)}, got {value!r}"
    )


def is_no_keys_getnewaddress(method: str, error: Exception) -> bool:
    message = getattr(error, "message", str(error))
    return (
        method == "getnewaddress"
        and getattr(error, "code", None) == -4
        and "no available keys" in message
    )


def install_descriptor_regtest_fallback(
    blockchaininterface: BlockchainInterface | None = None,
) -> bool:
    if blockchaininterface is None:
        # pylint: disable-next=import-error,import-outside-toplevel
        from jmclient import (
            blockchaininterface as imported_blockchaininterface,
        )

        blockchaininterface = cast(BlockchainInterface, imported_blockchaininterface)

    interface_class = blockchaininterface.RegtestBitcoinCoreInterface
    original_rpc = interface_class._rpc  # pylint: disable=protected-access
    if getattr(original_rpc, "_descriptor_regtest_fallback", False):
        return False

    def rpc_with_descriptor_regtest_fallback(
        self: RegtestBitcoinCoreInterface,
        method: str,
        params: list[object] | None = None,
    ) -> object:
        rpc_params = [] if params is None else params
        try:
            return original_rpc(self, method, rpc_params)
        except Exception as error:  # pylint: disable=broad-exception-caught
            if not is_no_keys_getnewaddress(method, error):
                raise

            original_url = self.jsonRpc.url
            try:
                self.jsonRpc.setURL("")
                loaded_wallets = cast(
                    Collection[str],
                    original_rpc(self, "listwallets", []),
                )
                if FUNDING_WALLET_NAME not in loaded_wallets:
                    original_rpc(self, "loadwallet", [FUNDING_WALLET_NAME])
                self.jsonRpc.setURL(FUNDING_WALLET_RPC_PATH)
                return original_rpc(self, "getnewaddress", [])
            finally:
                self.jsonRpc.setURL(original_url)

    patched_rpc = cast(PatchedRpcMethod, rpc_with_descriptor_regtest_fallback)
    patched_rpc._descriptor_regtest_fallback = True  # pylint: disable=protected-access
    interface_class._rpc = patched_rpc  # pylint: disable=protected-access
    return True


def parse_args(argv: list[str]) -> tuple[bool, list[str]]:
    parser = argparse.ArgumentParser(
        description="Run JoinMarket wallet RPC server with emulator runtime options"
    )
    fallback_group = parser.add_mutually_exclusive_group()
    fallback_group.add_argument(
        "--descriptor-regtest-fallback",
        dest="descriptor_regtest_fallback",
        action="store_true",
        default=None,
        help="use the Bitcoin Core funding wallet when the configured regtest wallet has no keys",
    )
    fallback_group.add_argument(
        "--no-descriptor-regtest-fallback",
        dest="descriptor_regtest_fallback",
        action="store_false",
        help="disable the descriptor-wallet regtest fallback",
    )

    args, jmwalletd_args = parser.parse_known_args(argv)
    if args.descriptor_regtest_fallback is None:
        enabled = parse_bool(os.getenv("JM_DESCRIPTOR_REGTEST_FALLBACK"), default=False)
    else:
        enabled = bool(args.descriptor_regtest_fallback)
    return enabled, jmwalletd_args


def main(argv: list[str] | None = None) -> int:
    enabled, jmwalletd_args = parse_args(sys.argv[1:] if argv is None else argv)
    if enabled:
        install_descriptor_regtest_fallback()
        log_info("Enabled JoinMarket descriptor regtest fallback")
    else:
        log_info("Disabled JoinMarket descriptor regtest fallback")

    sys.argv = [JMWALLETD_PATH, *jmwalletd_args]
    runpy.run_path(JMWALLETD_PATH, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
