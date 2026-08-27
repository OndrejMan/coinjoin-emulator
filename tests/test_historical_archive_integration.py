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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_ARCHIVE = "2025-04-02_12-15_dynamic-0.0paranoid-0seed--wallets--50.zip"
INTEGRATION_ENABLED = "RUN_HISTORICAL_ARCHIVE_INTEGRATION"


def _testing_data_dir() -> Path:
    return Path(os.environ.get("TESTING_DATA_DIR", WORKSPACE_ROOT / "testing_data"))


def _require_integration_archive() -> Path:
    if os.environ.get(INTEGRATION_ENABLED) != "1":
        pytest.skip(f"set {INTEGRATION_ENABLED}=1 to run the Docker integration test")
    archive_path = _testing_data_dir() / DEFAULT_ARCHIVE
    if not archive_path.is_file():
        pytest.skip(f"historical integration scenario is unavailable: {archive_path}")
    return archive_path


@pytest.mark.integration
def test_current_emulator_exports_a_valid_archive_for_a_historical_scenario(tmp_path: Path) -> None:
    """Run the current emulator and validate its newly exported archive."""
    source_archive = _require_integration_archive()
    with ZipFile(source_archive) as archive:
        scenario_name = next(name for name in archive.namelist() if name.endswith("/scenario.json"))
        scenario = json.loads(archive.read(scenario_name))

    scenario["name"] = f"historical-archive-regression-{uuid.uuid4().hex[:8]}"
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    logs_dir = PROJECT_ROOT / "logs"
    before = set(logs_dir.glob("*.zip")) if logs_dir.exists() else set()
    timeout_seconds = int(os.environ.get("HISTORICAL_ARCHIVE_INTEGRATION_TIMEOUT", "1800"))
    completed = subprocess.run(
        [sys.executable, "manager.py", "run", "--scenario", str(scenario_path)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    created_archives = set(logs_dir.glob("*.zip")) - before
    assert len(created_archives) == 1, f"expected one new emulator archive, found {created_archives}"

    corpus_dir = tmp_path / "generated-corpus"
    corpus_dir.mkdir()
    shutil.copy2(created_archives.pop(), corpus_dir)
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
