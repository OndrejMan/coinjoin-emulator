import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from tests import test_historical_archive_integration as replay
from tests.historical_archive_results import archive_results, compare_results


def _archive(path: Path, txid: str = "a" * 64, mined: bool = True) -> Path:
    root = "historical"
    scenario = {
        "name": "old",
        "rounds": 0,
        "blocks": 100,
        "default_version": "2.0.4",
        "wallets": [{"funds": [1000], "anon_score_target": 5}],
    }
    transaction = {"txid": txid, "vin": [{}, {}], "vout": [{}, {}, {}]}
    with ZipFile(path, "w") as archive:
        archive.writestr(f"{root}/scenario.json", json.dumps(scenario))
        archive.writestr(f"{root}/data/wasabi-backend/backend/WabiSabi/CoinJoinIdStore.txt", txid + "\n")
        archive.writestr(f"{root}/data/btc-node/block_0.json", json.dumps({"tx": [transaction] if mined else []}))
        archive.writestr(f"{root}/data/wasabi-client-000/coins.json", "[]")
    return path


def test_comparison_ignores_random_ids_and_block_count_but_measures_results(tmp_path):
    reference = archive_results(_archive(tmp_path / "old.zip"))
    actual = archive_results(_archive(tmp_path / "new.zip", "b" * 64))
    actual["exported_blocks"] += 3
    assert reference["broadcast_coinjoins"] == reference["mined_coinjoins"] == 1
    assert reference["coinjoin_inputs"] == 2
    assert reference["coinjoin_outputs"] == 3
    assert not compare_results(reference, actual, 0)["differences"]


def test_unmined_broadcast_does_not_count_as_confirmed(tmp_path):
    reference = archive_results(_archive(tmp_path / "old.zip"))
    actual = archive_results(_archive(tmp_path / "new.zip", mined=False))
    report = compare_results(reference, actual, 0.25)
    assert actual["broadcast_coinjoins"] == 1
    assert actual["mined_coinjoins"] == actual["coinjoin_inputs"] == actual["coinjoin_outputs"] == 0
    assert len(report["differences"]) == 3


@pytest.mark.parametrize("actual, passed", [(75, True), (125, True), (74, False), (126, False), (0, False)])
def test_tolerance_is_two_sided_and_rejects_no_progress(actual, passed):
    reference = dict(
        wallets=["wasabi-client-000"],
        broadcast_coinjoins=100,
        mined_coinjoins=100,
        coinjoin_inputs=200,
        coinjoin_outputs=300,
    )
    report = compare_results(reference, {**reference, "mined_coinjoins": actual}, 0.25)
    assert (not report["differences"]) == passed


def test_wallet_identity_is_exact_and_zero_reference_is_not_wildcard():
    reference = dict(
        wallets=["wasabi-client-000"], broadcast_coinjoins=0, mined_coinjoins=0, coinjoin_inputs=0, coinjoin_outputs=0
    )
    actual = {**reference, "wallets": ["wasabi-client-001"], "broadcast_coinjoins": 1}
    assert len(compare_results(reference, actual, 0.25)["differences"]) == 2


@pytest.mark.parametrize("tolerance", [-1, 1, float("nan"), float("inf")])
def test_invalid_tolerance_rejected(tolerance):
    with pytest.raises(ValueError):
        compare_results({}, {}, tolerance)


def test_missing_label_source_is_not_silently_zero(tmp_path):
    path = tmp_path / "empty.zip"
    with ZipFile(path, "w"):
        pass
    with pytest.raises(AssertionError, match="CoinJoinIdStore"):
        archive_results(path)


def test_opt_in_required_and_requested_missing_corpus_fails(monkeypatch):
    monkeypatch.delenv(replay.INTEGRATION_ENABLED, raising=False)
    with pytest.raises(pytest.skip.Exception):
        replay._require_integration_archive(None)
    monkeypatch.setenv(replay.INTEGRATION_ENABLED, "1")
    with pytest.raises(pytest.fail.Exception):
        replay._require_integration_archive(None)


@pytest.mark.parametrize("regression", [None, "coinjoins", "scenario", "contract"])
def test_replay_runs_manager_then_contract_and_persists_comparison(tmp_path, monkeypatch, regression):
    source = _archive(tmp_path / "source.zip")
    monkeypatch.setenv(replay.INTEGRATION_ENABLED, "1")
    monkeypatch.setenv("HISTORICAL_ARCHIVE_REL_TOLERANCE", "0.25")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setattr(replay, "PROJECT_ROOT", tmp_path)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if "manager.py" in command:
            scenario_path = Path(command[command.index("--scenario") + 1])
            scenario = replay.ScenarioConfig.from_json_config(scenario_path).to_dict()
            if regression == "scenario":
                scenario["blocks"] += 1
            output = scenario_path.parent / "coinjoin_emulator_data"
            output.mkdir()
            (output / "scenario.json").write_text(json.dumps(scenario))
            _archive(output / "emulation_logs.zip", mined=regression != "coinjoins")
            return subprocess.CompletedProcess(command, 0)
        assert command[-1] == "tests/test_historical_run_archives.py"
        assert list(Path(kwargs["env"]["TESTING_DATA_DIR"]).glob("*.zip"))
        return subprocess.CompletedProcess(command, int(regression == "contract"), "contract checked", "")

    monkeypatch.setattr(replay.subprocess, "run", run)
    if regression:
        with pytest.raises(
            AssertionError,
            match={
                "coinjoins": "mined_coinjoins",
                "scenario": "scenario differs",
                "contract": "artifact contract failed",
            }[regression],
        ):
            replay.test_current_emulator_replays_historical_results(source, tmp_path)
    else:
        replay.test_current_emulator_replays_historical_results(source, tmp_path)
    assert len(commands) == 2
    report = json.loads(next((tmp_path / "logs").glob("*/historical-comparison.json")).read_text())
    assert report["status"] == ("failed" if regression else "passed")
    assert report["source_archive"] == str(source)


def test_timeout_preserves_diagnostics_and_stops_batch(tmp_path, monkeypatch):
    source = _archive(tmp_path / "source.zip")
    monkeypatch.setenv(replay.INTEGRATION_ENABLED, "1")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setattr(replay, "PROJECT_ROOT", tmp_path)

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(replay.subprocess, "run", timeout)
    with pytest.raises(pytest.exit.Exception, match="Replay timed out"):
        replay.test_current_emulator_replays_historical_results(source, tmp_path)
    report_path = next((tmp_path / "logs").glob("*/historical-comparison.json"))
    assert json.loads(report_path.read_text())["status"] == "timeout"
    assert (report_path.parent / "replay.log").exists()
