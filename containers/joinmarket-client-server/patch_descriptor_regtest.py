#!/usr/bin/env python3
import sys
from pathlib import Path


DEFAULT_TARGET = Path("/jm/clientserver/src/jmclient/blockchaininterface.py")


def patch_blockchaininterface(path: Path) -> None:
    text = path.read_text()
    patched_marker = "def _get_regtest_mining_address"
    if patched_marker in text:
        print(f"{path} already has descriptor-regtest patch")
        return

    old = (
        '        self.destn_addr = self._rpc("getnewaddress", [])\n'
        "    def estimate_fee_per_kb"
    )
    new = (
        "        self.destn_addr = self._get_regtest_mining_address()\n\n"
        "    def _get_regtest_mining_address(self) -> str:\n"
        "        try:\n"
        '            return self._rpc("getnewaddress", [])\n'
        "        except JsonRpcError as e:\n"
        '            message = getattr(e, "message", str(e))\n'
        '            if getattr(e, "code", None) != -4 or "no available keys" not in message:\n'
        "                raise\n"
        "            original_url = self.jsonRpc.url\n"
        "            try:\n"
        '                self.jsonRpc.setURL("")\n'
        '                loaded_wallets = self._rpc("listwallets", [])\n'
        '                if "wallet" not in loaded_wallets:\n'
        '                    self._rpc("loadwallet", ["wallet"])\n'
        '                self.jsonRpc.setURL("/wallet/wallet")\n'
        '                return self._rpc("getnewaddress", [])\n'
        "            finally:\n"
        "                self.jsonRpc.setURL(original_url)\n\n"
        "    def estimate_fee_per_kb"
    )

    if old not in text:
        raise RuntimeError(
            f"Could not patch {path}; expected RegtestBitcoinCoreInterface "
            "getnewaddress block was not found"
        )

    path.write_text(text.replace(old, new, 1))
    print(f"patched {path} for descriptor-only regtest wallet startup")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TARGET
    patch_blockchaininterface(target)
