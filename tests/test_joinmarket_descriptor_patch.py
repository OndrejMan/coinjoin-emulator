import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PATCH_SCRIPT = PROJECT_ROOT / "containers" / "joinmarket-client-server" / "patch_descriptor_regtest.py"


class JoinMarketDescriptorPatchTest(unittest.TestCase):
    def test_patch_redirects_regtest_mining_address_to_funding_wallet(self):
        source = (
            "class RegtestBitcoinCoreInterface(BitcoinCoreInterface):\n"
            "    def __init__(self, jsonRpc, network):\n"
            "        super().__init__(jsonRpc, network)\n"
            '        self.destn_addr = self._rpc("getnewaddress", [])\n'
            "    def estimate_fee_per_kb(self, tx_fees, tx_vsize):\n"
            "        return 1000\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "blockchaininterface.py"
            target.write_text(source)

            subprocess.run(
                [sys.executable, str(PATCH_SCRIPT), str(target)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            patched = target.read_text()

        self.assertIn("self.destn_addr = self._get_regtest_mining_address()", patched)
        self.assertIn('self.jsonRpc.setURL("/wallet/wallet")', patched)
        self.assertIn('return self._rpc("getnewaddress", [])', patched)
        self.assertIn("def estimate_fee_per_kb", patched)


if __name__ == "__main__":
    unittest.main()
