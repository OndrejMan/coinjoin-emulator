import json
import unittest
from pathlib import Path


class DefaultJoinMarketScenarioTest(unittest.TestCase):
    def test_default_joinmarket_scenario_has_surplus_makers_and_rounds(self):
        scenario_path = (
            Path(__file__).resolve().parents[2]
            / "bitcoinAnalysis"
            / "scenarios"
            / "defaultJoinMarket.json"
        )
        scenario = json.loads(scenario_path.read_text())
        wallets = scenario["wallets"]
        takers = [wallet for wallet in wallets if wallet["joinmarket"]["role"] == "taker"]
        makers = [wallet for wallet in wallets if wallet["joinmarket"]["role"] == "maker"]

        self.assertEqual(scenario["rounds"], 3)
        self.assertEqual(scenario["blocks"], 0)
        self.assertEqual(scenario["default_version"], "joinmarket")
        self.assertGreaterEqual(len(takers), 2)
        self.assertGreaterEqual(len(makers), 8)
        for maker in makers:
            self.assertGreaterEqual(max(maker["funds"]), 30000)


if __name__ == "__main__":
    unittest.main()
