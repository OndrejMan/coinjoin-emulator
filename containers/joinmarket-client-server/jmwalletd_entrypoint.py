#!/usr/bin/env python3
"""Expose all derived wallet addresses to the emulator exporter."""
import runpy
import sys
from typing import Any

JMWALLETD_PATH = "/jm/clientserver/scripts/jmwalletd.py"


def install_display_all_addresses(wallet_rpc: Any = None) -> bool:
    """Make the wallet display include every derived address, including spent ones."""
    if wallet_rpc is None:
        from jmclient import wallet_rpc  # pylint: disable=import-error,import-outside-toplevel

    original_display = wallet_rpc.wallet_display
    if getattr(original_display, "_display_all_addresses", False):
        return False

    def wallet_display_all(wallet_service: Any, showprivkey: bool, *args: Any, **kwargs: Any) -> Any:
        if args:
            args = (True, *args[1:])
        else:
            kwargs["displayall"] = True
        return original_display(wallet_service, showprivkey, *args, **kwargs)

    wallet_display_all._display_all_addresses = True  # type: ignore[attr-defined]
    wallet_rpc.wallet_display = wallet_display_all
    return True


def main() -> int:
    install_display_all_addresses()
    sys.argv = [JMWALLETD_PATH, *sys.argv[1:]]
    runpy.run_path(JMWALLETD_PATH, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
