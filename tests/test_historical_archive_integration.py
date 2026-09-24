"""Opt-in live regression tests for every ZIP in the historical corpus.

Run with ``RUN_HISTORICAL_ARCHIVE_INTEGRATION=1``. Compare archive contracts
and aggregate CoinJoin outcomes with a configurable
tolerance. The tolerance is a regression threshold, not a statistical guarantee.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from zipfile import ZipFile

import pytest

from manager.engine.configuration import ScenarioConfig, WasabiConfig
from tests.historical_archive_results import archive_results, compare_results

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
INTEGRATION_ENABLED = "RUN_HISTORICAL_ARCHIVE_INTEGRATION"
LEGACY_WASABI_FIELDS = ("anon_score_target", "redcoin_isolation", "skip_rounds")
MAX_RUN_ID_LENGTH = 63


def _testing_data_dir() -> Path:
    return Path(os.environ.get("TESTING_DATA_DIR", WORKSPACE_ROOT / "testing_data"))


def _require_integration_archive(archive_path: Path | None) -> Path:
    if os.environ.get(INTEGRATION_ENABLED) != "1":
        pytest.skip(f"set {INTEGRATION_ENABLED}=1 to run the Docker integration test")
    if archive_path is None or not archive_path.is_file():
        pytest.fail(f"no historical integration archives available in {_testing_data_dir()}")
    if os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.fail("historical Docker replays must run sequentially (without pytest-xdist)")
    return archive_path


def _replay_run_id(source_archive: Path, suffix: str) -> str:
    """Keep the unique suffix while fitting manager.py's 63-character run ID limit."""
    prefix = f"hist-{suffix}-"
    return (prefix + source_archive.stem)[:MAX_RUN_ID_LENGTH].rstrip("-._")


def _migrate_legacy_wasabi_settings(scenario: dict[str, object]) -> None:
    """Convert archived flat wallet settings to the current scenario schema."""
    wallets = scenario.get("wallets")
    if not isinstance(wallets, list):
        return
    for wallet in wallets:
        if not isinstance(wallet, dict):
            continue
        wasabi = wallet.get("wasabi")
        nested = dict(wasabi) if isinstance(wasabi, dict) else {}
        for field in LEGACY_WASABI_FIELDS:
            if field in wallet:
                nested.setdefault(field, wallet.pop(field))
        if nested:
            wallet["wasabi"] = nested


def _load_replay_scenario(source_archive: Path, run_id: str) -> dict[str, object]:
    with ZipFile(source_archive) as archive:
        scenario_name = next(name for name in archive.namelist() if name.endswith("/scenario.json"))
        scenario = json.loads(archive.read(scenario_name))
    _migrate_legacy_wasabi_settings(scenario)
    scenario["name"] = run_id
    return scenario


def test_legacy_wasabi_settings_are_migrated_before_replay(tmp_path: Path) -> None:
    scenario: dict[str, object] = {
        "name": "historical",
        "rounds": 10,
        "blocks": 0,
        "default_version": "2.6.0",
        "wallets": [
            {
                "funds": [1000],
                "anon_score_target": 5,
                "redcoin_isolation": False,
                "skip_rounds": [0, 2],
            }
        ],
    }

    archive_path = tmp_path / "historical.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("historical/scenario.json", json.dumps(scenario))

    migrated = _load_replay_scenario(archive_path, "replayed-run")
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(migrated), encoding="utf-8")
    parsed = ScenarioConfig.from_json_config(scenario_path)

    assert migrated["name"] == "replayed-run"
    assert migrated["wallets"] == [
        {
            "funds": [1000],
            "wasabi": {
                "anon_score_target": 5,
                "redcoin_isolation": False,
                "skip_rounds": [0, 2],
            },
        }
    ]
    assert parsed.wallets[0].wasabi == WasabiConfig(
        anon_score_target=5,
        redcoin_isolation=False,
        skip_rounds=[0, 2],
    )


def test_replay_run_id_fits_manager_limit() -> None:
    archive = Path("2025-03-22_06-11_dynamic-0.0paranoid-10seed--wallets--25.zip")

    run_id = _replay_run_id(archive, "f7907728")

    assert run_id.startswith("hist-f7907728-2025-03-22_06-11_dynamic")
    assert len(run_id) <= MAX_RUN_ID_LENGTH
    assert run_id[-1].isalnum()


@pytest.mark.integration
@pytest.mark.parametrize(
    "source_archive",
    sorted(_testing_data_dir().glob("*.zip")) or [None],
    ids=lambda path: path.stem if path is not None else "missing-corpus",
)
def test_current_emulator_replays_historical_results(source_archive: Path | None, tmp_path: Path) -> None:
    """Replay each historical scenario and compare the newly exported outcome."""
    source_archive = _require_integration_archive(source_archive)
    tolerance = float(os.environ.get("HISTORICAL_ARCHIVE_REL_TOLERANCE", "0.25"))
    assert math.isfinite(tolerance) and 0 <= tolerance < 1, "tolerance must be finite and in [0, 1)"
    timeout_seconds = int(os.environ.get("HISTORICAL_ARCHIVE_INTEGRATION_TIMEOUT", "86400"))
    assert timeout_seconds > 0
    reference = archive_results(source_archive)
    run_id = _replay_run_id(source_archive, uuid.uuid4().hex[:8])
    run_path = PROJECT_ROOT / "logs" / run_id
    run_path.mkdir(parents=True)
    scenario = _load_replay_scenario(source_archive, run_id)
    scenario_path = run_path / "replay-scenario.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    expected_scenario = ScenarioConfig.from_json_config(scenario_path).to_dict()
    command = [
        sys.executable,
        "-u",
        "manager.py",
        "--engine",
        "wasabi",
        "--driver",
        "docker",
        "run",
        "--run-id",
        run_id,
        "--scenario",
        str(scenario_path),
    ]
    report_path = run_path / "historical-comparison.json"
    report = {
        "source_archive": str(source_archive.resolve()),
        "command": command,
        "relative_tolerance": tolerance,
        "reference": reference,
        "status": "running",
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log_path = run_path / "replay.log"
    with log_path.open("w", encoding="utf-8") as log:
        try:
            completed = subprocess.run(
                command, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout_seconds, check=False
            )
        except subprocess.TimeoutExpired:
            report["status"] = "timeout"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            pytest.exit(
                f"Replay timed out; inspect {log_path} and remaining containers before restarting", returncode=1
            )
    report["status"] = "failed"
    report["returncode"] = completed.returncode
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert completed.returncode == 0, f"emulator failed; see {log_path}"

    created_archive = run_path / "coinjoin_emulator_data" / "emulation_logs.zip"
    assert created_archive.is_file(), f"expected emulator archive at {created_archive}"
    actual_scenario = ScenarioConfig.from_json_config(created_archive.parent / "scenario.json").to_dict()
    comparison = compare_results(reference, archive_results(created_archive), tolerance)
    if actual_scenario != expected_scenario:
        comparison["differences"].append("exported scenario differs from the replay scenario")
    report.update(comparison)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    corpus_dir = tmp_path / "generated-corpus"
    corpus_dir.mkdir()
    shutil.copy2(created_archive, corpus_dir)
    contract = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_historical_run_archives.py"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
        env={**os.environ, "TESTING_DATA_DIR": str(corpus_dir)},
    )
    (run_path / "artifact-contract.log").write_text(contract.stdout + contract.stderr, encoding="utf-8")
    if contract.returncode:
        report["differences"].append("artifact contract failed; see artifact-contract.log")
    report["status"] = "passed" if not report["differences"] else "failed"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not report["differences"], f"{report['differences']}; see {report_path}"
