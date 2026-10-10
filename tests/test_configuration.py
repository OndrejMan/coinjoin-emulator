"""Scenario file parsing contracts."""

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
    config = load_scenario(
        tmp_path,
        base_scenario(
            {
                "funds": [1000],
                "wasabi": {"anon_score_target": 42, "redcoin_isolation": True, "skip_rounds": [0, 2]},
            }
        ),
    )

    reloaded = load_scenario(tmp_path, config.to_dict())

    assert reloaded.wallets[0].wasabi == config.wallets[0].wasabi

@pytest.mark.parametrize("field", ["anon_score_target", "redcoin_isolation", "skip_rounds"])
def test_flat_wasabi_settings_are_rejected(tmp_path: Path, field: str) -> None:
    with pytest.raises(ValueError, match="flat Wasabi wallet settings"):
        load_scenario(tmp_path, base_scenario({"funds": [1000], field: "legacy"}))


def test_nested_joinmarket_experiment_config_round_trips(tmp_path: Path) -> None:
    config = load_scenario(
        tmp_path,
        base_scenario(
            {
                "funds": [1000],
                "joinmarket": {
                    "role": "maker",
                    "offers": [{"ordertype": "sw0reloffer", "minsize": 1000}],
                    "tumbler_options": {"mixdepthcount": 3},
                    "time_between_rounds": 4,
                    "coinjoin_timeout_blocks": 12,
                    "fidelity_bond": {"enabled": True},
                    "max_coinjoins": 2,
                },
            }
        ),
    )

    joinmarket = load_scenario(tmp_path, config.to_dict()).wallets[0].joinmarket

    assert joinmarket is not None
    assert joinmarket.role is JoinMarketRole.MAKER
    assert joinmarket.offers == [{"ordertype": "sw0reloffer", "minsize": 1000}]
    assert joinmarket.coinjoin_timeout_blocks == 12
    assert joinmarket.fidelity_bond == {"enabled": True}
    assert joinmarket.max_coinjoins == 2


def test_invalid_joinmarket_role_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid JoinMarket role"):
        load_scenario(tmp_path, base_scenario({"funds": [1000], "joinmarket": {"role": "observer"}}))


@pytest.mark.parametrize(
    "field",
    ["type", "offers", "tumbler_options", "time_between_rounds", "coinjoin_timeout_blocks", "fidelity_bond", "max_coinjoins"],
)
def test_flat_joinmarket_settings_are_rejected(tmp_path: Path, field: str) -> None:
    with pytest.raises(ValueError, match="flat JoinMarket wallet settings"):
        load_scenario(tmp_path, base_scenario({"funds": [1000], field: "legacy"}))


@pytest.mark.parametrize("timeout_blocks", [0, -1, True, "8"])
def test_joinmarket_timeout_must_be_a_positive_integer(tmp_path: Path, timeout_blocks: object) -> None:
    with pytest.raises(ValueError, match="coinjoin_timeout_blocks"):
        load_scenario(
            tmp_path,
            base_scenario(
                {
                    "funds": [1000],
                    "joinmarket": {
                        "role": "taker",
                        "coinjoin_timeout_blocks": timeout_blocks,
                    },
                }
            ),
        )


def test_joinmarket_engine_requires_explicit_roles(tmp_path: Path) -> None:
    config = load_scenario(tmp_path, base_scenario({"funds": [1000]}))

    config.validate_for_engine("wasabi")
    with pytest.raises(ValueError, match="explicit maker/taker role"):
        config.validate_for_engine("joinmarket")


def test_round_limited_tumbler_requires_a_block_limit(tmp_path: Path) -> None:
    settings = {"tumbler_options": {"mixdepthcount": 3}}
    wallet = {"joinmarket": {"role": "taker", **settings}}
    config = load_scenario(tmp_path, base_scenario({"funds": [1000], **wallet}))

    with pytest.raises(ValueError, match="require blocks > 0"):
        config.validate_for_engine("joinmarket")

    config.blocks = 30
    config.validate_for_engine("joinmarket")


def test_regular_taker_can_still_use_only_a_round_limit(tmp_path: Path) -> None:
    config = load_scenario(tmp_path, base_scenario({"funds": [1000], "joinmarket": {"role": "taker"}}))
    config.validate_for_engine("joinmarket")


def test_postmix_spend_schedule_round_trips(tmp_path: Path) -> None:
    spends = [
        {"value": 50_000_000, "delay_rounds": 12},
        {"all": True, "delay_blocks": 30, "delay_rounds": 20, "min_anon_score": 5},
    ]
    config = load_scenario(tmp_path, base_scenario({"funds": [1000], "wasabi": {"postmix_spends": spends}}))

    reloaded = load_scenario(tmp_path, config.to_dict()).wallets[0].wasabi

    assert reloaded is not None
    assert reloaded.postmix_spends == config.wallets[0].wasabi.postmix_spends
    assert [spend.all for spend in reloaded.postmix_spends] == [False, True]
    assert reloaded.postmix_spends[0].value == 50_000_000
    assert reloaded.postmix_spends[1].min_anon_score == 5


@pytest.mark.parametrize(
    ("spend", "message"),
    [
        ({"delay_rounds": 3}, "exactly one of 'value' and 'all'"),
        ({"value": 1000, "all": True}, "exactly one of 'value' and 'all'"),
        ({"value": 0}, "positive integer of satoshis"),
        ({"value": True}, "positive integer of satoshis"),
        ({"all": "yes"}, "must be a boolean"),
        ({"all": True, "delay_rounds": -1}, "delay_rounds must be a non-negative integer"),
        ({"all": True, "min_anon_score": 0}, "min_anon_score must be a positive number"),
        ({"all": True, "destination": "x"}, "unknown fields: destination"),
    ],
)
def test_invalid_postmix_spends_are_rejected(tmp_path: Path, spend: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_scenario(tmp_path, base_scenario({"funds": [1000], "wasabi": {"postmix_spends": [spend]}}))


@pytest.mark.parametrize("wasabi", [{"postmix_spends": [{"all": True}]}, {"anon_score_target": 5}])
def test_wasabi_settings_are_rejected_for_joinmarket(tmp_path: Path, wasabi: dict[str, object]) -> None:
    wallet = {"funds": [1000], "joinmarket": {"role": "taker"}, "wasabi": wasabi}
    config = load_scenario(tmp_path, base_scenario(wallet))

    config.validate_for_engine("wasabi")
    with pytest.raises(ValueError, match="ignored by the JoinMarket engine; remove them at indexes: 0"):
        config.validate_for_engine("joinmarket")
