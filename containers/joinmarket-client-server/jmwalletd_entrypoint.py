#!/usr/bin/env python3
import argparse
import os
import runpy
import sys
from types import ModuleType
from typing import Any

JMWALLETD_PATH = "/jm/clientserver/scripts/jmwalletd.py"
FUNDING_WALLET_RPC_PATH = "/wallet/wallet"
FUNDING_WALLET_NAME = "wallet"

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


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
    blockchaininterface: ModuleType | None = None,
) -> bool:
    if blockchaininterface is None:
        from jmclient import blockchaininterface as imported_blockchaininterface

        blockchaininterface = imported_blockchaininterface

    interface_class = blockchaininterface.RegtestBitcoinCoreInterface
    original_rpc = interface_class._rpc
    if getattr(original_rpc, "_descriptor_regtest_fallback", False):
        return False

    def rpc_with_descriptor_regtest_fallback(
        self: Any,
        method: str,
        params: list[object],
    ) -> object:
        try:
            return original_rpc(self, method, params)
        except Exception as error:
            if not is_no_keys_getnewaddress(method, error):
                raise

            original_url = self.jsonRpc.url
            try:
                self.jsonRpc.setURL("")
                loaded_wallets = original_rpc(self, "listwallets", [])
                if FUNDING_WALLET_NAME not in loaded_wallets:
                    original_rpc(self, "loadwallet", [FUNDING_WALLET_NAME])
                self.jsonRpc.setURL(FUNDING_WALLET_RPC_PATH)
                return original_rpc(self, "getnewaddress", [])
            finally:
                self.jsonRpc.setURL(original_url)

    rpc_with_descriptor_regtest_fallback._descriptor_regtest_fallback = True
    interface_class._rpc = rpc_with_descriptor_regtest_fallback
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
        print("Enabled JoinMarket descriptor regtest fallback")
    else:
        print("Disabled JoinMarket descriptor regtest fallback")

    sys.argv = [JMWALLETD_PATH, *jmwalletd_args]
    runpy.run_path(JMWALLETD_PATH, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
