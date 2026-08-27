import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from manager.engine.configuration import JoinMarketRole, ScenarioConfig


class ScenarioConfigTest(unittest.TestCase):
    def load_scenario(self, scenario: dict[str, object]) -> ScenarioConfig:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            return ScenarioConfig.from_json_config(path)

    def test_nested_wasabi_wallet_config_is_parsed(self) -> None:
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

    def test_flat_wasabi_wallet_config_still_works(self) -> None:
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

    def test_nested_joinmarket_wallet_config_is_parsed(self) -> None:
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

    def test_to_dict_serializes_joinmarket_role_as_json_value(self) -> None:
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

    def test_wallets_are_required_and_non_empty(self) -> None:
        base = {"name": "invalid", "rounds": 1, "blocks": 0, "default_version": "2.6.0"}
        with self.assertRaisesRegex(ValueError, "wallets"):
            self.load_scenario(base)
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            self.load_scenario({**base, "wallets": []})

    def test_negative_limits_are_rejected(self) -> None:
        scenario = {
            "name": "invalid",
            "rounds": -1,
            "blocks": 0,
            "default_version": "2.6.0",
            "wallets": [{"funds": [1000]}],
        }
        with self.assertRaisesRegex(ValueError, "rounds must be a non-negative integer"):
            self.load_scenario(scenario)

    def test_string_boolean_is_rejected(self) -> None:
        scenario = {
            "name": "invalid",
            "rounds": 1,
            "blocks": 0,
            "default_version": "2.6.0",
            "default_redcoin_isolation": "false",
            "wallets": [{"funds": [1000]}],
        }
        with self.assertRaisesRegex(ValueError, "boolean option"):
            self.load_scenario(scenario)

    def test_joinmarket_wallet_role_is_required(self) -> None:
        scenario = {
            "name": "invalid-joinmarket",
            "rounds": 1,
            "blocks": 0,
            "default_version": "2.6.0",
            "wallets": [{"funds": [1000]}],
        }
        config = self.load_scenario(scenario)
        config.validate_for_engine("wasabi")
        with self.assertRaisesRegex(ValueError, "explicit maker/taker role"):
            config.validate_for_engine("joinmarket")

    def test_joinmarket_roles_are_validated_for_selected_engine_not_version_name(self) -> None:
        scenario = {
            "name": "joinmarket-custom-version",
            "rounds": 1,
            "blocks": 0,
            "default_version": "custom-image-tag",
            "wallets": [{"funds": [1000], "joinmarket": {"role": "taker"}}],
        }

        config = self.load_scenario(scenario)
        config.validate_for_engine("joinmarket")


if __name__ == "__main__":
    unittest.main()
