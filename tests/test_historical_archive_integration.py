"""Opt-in live regression test using a scenario from the historical corpus.

Run with ``RUN_HISTORICAL_ARCHIVE_INTEGRATION=1``.  The test intentionally
compares the new archive's structure, not its transaction IDs, because live
CoinJoin runs are nondeterministic.
"""

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from zipfile import ZipFile

import pytest

from manager.engine.configuration import ScenarioConfig, WasabiConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_ARCHIVE = "2025-04-02_12-15_dynamic-0.0paranoid-0seed--wallets--50.zip"
INTEGRATION_ENABLED = "RUN_HISTORICAL_ARCHIVE_INTEGRATION"
LEGACY_WASABI_FIELDS = ("anon_score_target", "redcoin_isolation", "skip_rounds")


def _testing_data_dir() -> Path:
    return Path(os.environ.get("TESTING_DATA_DIR", WORKSPACE_ROOT / "testing_data"))


def _require_integration_archive() -> Path:
    if os.environ.get(INTEGRATION_ENABLED) != "1":
        pytest.skip(f"set {INTEGRATION_ENABLED}=1 to run the Docker integration test")
    archive_path = _testing_data_dir() / DEFAULT_ARCHIVE
    if not archive_path.is_file():
        pytest.skip(f"historical integration scenario is unavailable: {archive_path}")
    return archive_path


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
        ]
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


@pytest.mark.integration
def test_current_emulator_exports_a_valid_archive_for_a_historical_scenario(tmp_path: Path) -> None:
    """Run the current emulator and validate its newly exported archive."""
    source_archive = _require_integration_archive()
    run_id = f"historical-archive-regression-{uuid.uuid4().hex[:8]}"
    scenario = _load_replay_scenario(source_archive, run_id)
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    timeout_seconds = int(os.environ.get("HISTORICAL_ARCHIVE_INTEGRATION_TIMEOUT", "1800"))
    completed = subprocess.run(
        [
            sys.executable,
            "manager.py",
            "run",
            "--run-id",
            run_id,
            "--scenario",
            str(scenario_path),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    created_archive = PROJECT_ROOT / "logs" / run_id / "coinjoin_emulator_data" / "emulation_logs.zip"
    assert created_archive.is_file(), f"expected emulator archive at {created_archive}"

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
    assert contract.returncode == 0, contract.stdout + contract.stderr
