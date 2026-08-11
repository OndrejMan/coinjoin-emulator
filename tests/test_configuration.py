import json
from pathlib import Path

import pytest

from manager.engine.configuration import JoinMarketRole, ScenarioConfig


def load_scenario(tmp_path: Path, scenario: dict[str, object]) -> ScenarioConfig:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    return ScenarioConfig.from_json_config(path)


def base_scenario(wallet: dict[str, object]) -> dict[str, object]:
    return {
        "name": "test",
        "rounds": 1,
        "blocks": 0,
        "default_version": "joinmarket",
        "wallets": [wallet],
    }


def test_nested_wasabi_config_round_trips(tmp_path: Path) -> None:
    original = base_scenario(
        {
            "funds": [1000],
            "wasabi": {
                "anon_score_target": 42,
                "redcoin_isolation": True,
                "skip_rounds": [0, 2],
            },
        }
    )

    config = load_scenario(tmp_path, original)
    reloaded = load_scenario(tmp_path, config.to_dict())

    assert reloaded.wallets[0].wasabi == config.wallets[0].wasabi


def test_nested_joinmarket_experiment_config_round_trips(tmp_path: Path) -> None:
    original = base_scenario(
        {
            "funds": [1000],
            "joinmarket": {
                "role": "maker",
                "offers": [{"ordertype": "sw0reloffer", "minsize": 1000}],
                "tumbler_options": {"mixdepthcount": 3},
                "time_between_rounds": 4,
                "fidelity_bond": {"enabled": True},
                "max_coinjoins": 2,
            },
        }
    )

    config = load_scenario(tmp_path, original)
    reloaded = load_scenario(tmp_path, config.to_dict())
    joinmarket = reloaded.wallets[0].joinmarket

    assert joinmarket is not None
    assert joinmarket.role is JoinMarketRole.MAKER
    assert joinmarket.offers == [{"ordertype": "sw0reloffer", "minsize": 1000}]
    assert joinmarket.fidelity_bond == {"enabled": True}
    assert joinmarket.max_coinjoins == 2


def test_invalid_joinmarket_role_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid JoinMarket role"):
        load_scenario(tmp_path, base_scenario({"funds": [1000], "type": "observer"}))


@pytest.mark.parametrize("field", ["rounds", "blocks"])
def test_negative_scenario_limits_are_rejected(tmp_path: Path, field: str) -> None:
    scenario = base_scenario({"funds": [1000]})
    scenario[field] = -1

    with pytest.raises(ValueError, match=f"{field} must be a non-negative integer"):
        load_scenario(tmp_path, scenario)


def test_wallets_and_positive_funds_are_required(tmp_path: Path) -> None:
    scenario = base_scenario({"funds": [1000]})
    scenario["wallets"] = []
    with pytest.raises(ValueError, match="wallets must be a non-empty list"):
        load_scenario(tmp_path, scenario)

    with pytest.raises(ValueError, match="positive integer"):
        load_scenario(tmp_path, base_scenario({"funds": [0]}))


def test_joinmarket_engine_requires_explicit_roles(tmp_path: Path) -> None:
    config = load_scenario(tmp_path, base_scenario({"funds": [1000]}))

    config.validate_for_engine("wasabi")
    with pytest.raises(ValueError, match="explicit maker/taker role"):
        config.validate_for_engine("joinmarket")
