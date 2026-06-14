import json
import unittest
from pathlib import Path


class DefaultJoinMarketScenarioTest(unittest.TestCase):
    def test_default_joinmarket_scenario_is_minimal_four_maker_round(self):
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

        self.assertEqual(scenario["rounds"], 1)
        self.assertEqual(scenario["blocks"], 0)
        self.assertEqual(scenario["default_version"], "joinmarket")
        self.assertEqual(len(takers), 1)
        self.assertEqual(len(makers), 4)
        for maker in makers:
            self.assertGreaterEqual(max(maker["funds"]), 30000)


if __name__ == "__main__":
    unittest.main()
