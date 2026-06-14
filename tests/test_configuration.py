import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from manager.engine.configuration import JoinMarketRole, ScenarioConfig


class ScenarioConfigTest(unittest.TestCase):
    def test_nested_wasabi_wallet_config_is_parsed(self):
        scenario = {
            "name": "nested",
            "rounds": 1,
            "blocks": 0,
            "default_version": "2.6.0",
            "wallets": [
                {
                    "funds": [1000],
                    "wasabi": {
                        "anon_score_target": 42,
                        "redcoin_isolation": True,
                        "skip_rounds": [0, 2],
                    },
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            config = ScenarioConfig.from_json_config(path)

        wallet = config.wallets[0]
        self.assertIsNotNone(wallet.wasabi)
        wasabi = wallet.wasabi
        assert wasabi is not None
        self.assertEqual(wasabi.anon_score_target, 42)
        self.assertTrue(wasabi.redcoin_isolation)
        self.assertEqual(wasabi.skip_rounds, [0, 2])

    def test_flat_wasabi_wallet_config_still_works(self):
        scenario = {
            "name": "flat",
            "rounds": 1,
            "blocks": 0,
            "default_version": "2.6.0",
            "wallets": [
                {
                    "funds": [1000],
                    "anon_score_target": 7,
                    "redcoin_isolation": False,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            config = ScenarioConfig.from_json_config(path)

        wallet = config.wallets[0]
        self.assertIsNotNone(wallet.wasabi)
        wasabi = wallet.wasabi
        assert wasabi is not None
        self.assertEqual(wasabi.anon_score_target, 7)
        self.assertFalse(wasabi.redcoin_isolation)

    def test_nested_joinmarket_wallet_config_is_parsed(self):
        scenario = {
            "name": "joinmarket",
            "rounds": 1,
            "blocks": 0,
            "default_version": "latest",
            "wallets": [
                {
                    "funds": [1000],
                    "joinmarket": {"role": "maker"},
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            config = ScenarioConfig.from_json_config(path)

        wallet = config.wallets[0]
        self.assertIsNotNone(wallet.joinmarket)
        joinmarket = wallet.joinmarket
        assert joinmarket is not None
        self.assertEqual(joinmarket.role, JoinMarketRole.MAKER)

    def test_to_dict_serializes_joinmarket_role_as_json_value(self):
        scenario = {
            "name": "joinmarket",
            "rounds": 1,
            "blocks": 0,
            "default_version": "latest",
            "wallets": [
                {
                    "funds": [1000],
                    "joinmarket": {"role": "maker"},
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            config = ScenarioConfig.from_json_config(path)

        serialized = config.to_dict()
        wallets = cast(list[dict[str, object]], serialized["wallets"])
        joinmarket = cast(dict[str, object], wallets[0]["joinmarket"])
        self.assertEqual(joinmarket["role"], "maker")
        json.dumps(serialized)


if __name__ == "__main__":
    unittest.main()
