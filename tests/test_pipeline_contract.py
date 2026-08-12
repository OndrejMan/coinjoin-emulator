"""Tests for the pipeline contract ported onto this branch.

These cover the parts the coinjoin-pipeline depends on: a deterministic run
directory, the controller markers, the emulator artifact layout, and the
producer-owned ground truth (round events plus the label manifest).
"""

import importlib.util
import json
import os
import sys
import types
import zipfile
from pathlib import Path
from typing import cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from manager.btc_node import BtcNode  # noqa: E402
from manager.driver import Driver  # noqa: E402
from manager.engine.base.manifest import write_producer_label_manifest  # noqa: E402
from manager.engine.base.protocols import EmulatorClient  # noqa: E402
from manager.engine.configuration import ScenarioConfig, WalletConfig  # noqa: E402
from manager.engine.engine_base import EngineBase  # noqa: E402
from manager.engine.joinmarket_engine import JoinmarketEngine  # noqa: E402


def load_entrypoint() -> types.ModuleType:
    """Import manager.py, which shares its name with the manager package."""
    spec = importlib.util.spec_from_file_location("manager_entrypoint", PROJECT_ROOT / "manager.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeNode:
    def __init__(self, blocks: int = 2) -> None:
        self.blocks = blocks

    def get_block_count(self) -> int:
        return self.blocks

    def get_block_hash(self, height: int) -> str:
        return f"hash-{height}"

    def get_block_info(self, block_hash: str) -> dict[str, object]:
        return {"hash": block_hash, "height": 1}


class RecordingEngine(EngineBase):
    """Minimal concrete engine: everything the artifact layout needs, nothing else."""

    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig(
            name="scenario",
            rounds=1,
            blocks=0,
            default_version="v",
            wallets=[WalletConfig(funds=[1000])],
        )

    def store_engine_logs(self, data_path: str) -> dict[str, object] | None:
        with open(os.path.join(data_path, "engine.json"), "w", encoding="utf-8") as stream:
            json.dump({"engine": "recording"}, stream)
        return None


def make_engine(run_id: str | None = None, no_logs: bool = False) -> RecordingEngine:
    args = types.SimpleNamespace(command="run", scenario=None, run_id=run_id, no_logs=no_logs)
    engine = RecordingEngine(args, cast(Driver, None), "/src")
    engine.node = cast(BtcNode, FakeNode())
    engine.clients = []
    return engine


# --- run IDs ---------------------------------------------------------------

@pytest.mark.parametrize("value", ["run-1", "2026-08-03_scenario", "a", "a.b_c-d"])
def test_run_id_accepts_safe_names(value: str) -> None:
    assert load_entrypoint().run_id(value) == value


@pytest.mark.parametrize("value", ["../escape", "-leading", "trailing-", "a/b", "a" * 64, "a..b"])
def test_run_id_rejects_unsafe_names(value: str) -> None:
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        load_entrypoint().run_id(value)


def test_log_run_path_uses_the_requested_run_id() -> None:
    assert make_engine(run_id="pinned").log_run_path() == "./logs/pinned"


def test_log_run_path_falls_back_to_timestamp_and_scenario_name() -> None:
    path = make_engine().log_run_path()
    assert path.startswith("./logs/")
    assert path.endswith("_scenario")


# --- controller markers ----------------------------------------------------

def test_controller_marker_is_written_for_the_matching_outcome(tmp_path: Path) -> None:
    entrypoint = load_entrypoint()
    done = tmp_path / "nested" / "done.marker"
    failed = tmp_path / "nested" / "failed.marker"
    setattr(entrypoint, "args", types.SimpleNamespace(
        controller_done_marker=str(done), controller_failed_marker=str(failed)
    ))

    assert entrypoint.finalize_controller_marker(0) == 0
    assert done.exists() and not failed.exists()

    done.unlink()
    assert entrypoint.finalize_controller_marker(1) == 1
    assert failed.exists() and not done.exists()


def test_controller_markers_are_optional(tmp_path: Path) -> None:
    entrypoint = load_entrypoint()
    setattr(entrypoint, "args", types.SimpleNamespace(controller_done_marker="", controller_failed_marker=""))
    assert entrypoint.finalize_controller_marker(0) == 0
    assert list(tmp_path.iterdir()) == []


# --- artifact layout -------------------------------------------------------

def test_store_logs_writes_the_emulator_artifact_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    make_engine(run_id="my-run").store_logs()

    run_path = tmp_path / "logs" / "my-run"
    experiment = run_path / "coinjoin_emulator_data"
    assert sorted(p.name for p in run_path.iterdir()) == ["coinjoin_emulator_data"]
    assert sorted(p.name for p in experiment.iterdir()) == [
        "data",
        "emulation_logs.zip",
        "scenario.json",
    ]
    assert (experiment / "data" / "btc-node" / "block_0.json").is_file()

    with zipfile.ZipFile(experiment / "emulation_logs.zip") as archive:
        roots = {name.split("/")[0] for name in archive.namelist()}
    assert roots == {"coinjoin_emulator_data"}


def test_run_refuses_to_overwrite_an_existing_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    engine = make_engine(run_id="my-run")
    engine.ensure_log_run_path_available()
    engine.store_logs()

    with pytest.raises(RuntimeError, match="already exists"):
        engine.ensure_log_run_path_available()


def test_a_prepared_run_directory_without_artifacts_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs" / "my-run").mkdir(parents=True)
    (tmp_path / "logs" / "my-run" / "host_manifest.json").write_text("{}", encoding="utf-8")

    make_engine(run_id="my-run").ensure_log_run_path_available()


# --- producer-label manifest ----------------------------------------------

def test_manifest_records_sources_with_their_digest(tmp_path: Path) -> None:
    source = tmp_path / "labels.json"
    source.write_text("[]", encoding="utf-8")
    write_producer_label_manifest(
        str(tmp_path),
        {
            "engine": "joinmarket",
            "complete": True,
            "reason": None,
            "positive_rule": "rule",
            "positive_count": 1,
            "sources": ["labels.json"],
        },
    )

    manifest = json.loads((tmp_path / "coinjoin_label_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0"
    assert manifest["complete"] is True
    assert manifest["sources"][0]["path"] == "labels.json"
    assert len(manifest["sources"][0]["sha256"]) == 64


def test_manifest_is_incomplete_without_evidence(tmp_path: Path) -> None:
    write_producer_label_manifest(str(tmp_path), None)
    manifest = json.loads((tmp_path / "coinjoin_label_manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["reason"]


def test_manifest_rejects_sources_outside_the_data_directory(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    write_producer_label_manifest(
        str(tmp_path),
        {"engine": "joinmarket", "complete": True, "sources": ["../outside.json"]},
    )

    manifest = json.loads((tmp_path / "coinjoin_label_manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["sources"] == []


# --- JoinMarket round events ----------------------------------------------

def make_joinmarket_engine(round_events: list[dict[str, object]]) -> JoinmarketEngine:
    engine = object.__new__(JoinmarketEngine)
    engine.clients = [cast(EmulatorClient, types.SimpleNamespace(round_events=round_events))]
    engine.obwatch_client = None
    return engine


def write_block(node_path: str, height: int, txid: str, address: str) -> None:
    with open(os.path.join(node_path, f"block_{height}.json"), "w", encoding="utf-8") as stream:
        json.dump(
            {"height": height, "tx": [{"txid": txid, "vout": [{"scriptPubKey": {"address": address}}]}]},
            stream,
        )


def test_round_events_are_matched_to_the_exported_blocks(tmp_path: Path) -> None:
    node_path = tmp_path / "btc-node"
    node_path.mkdir()
    write_block(str(node_path), 7, "a" * 64, "bcrt1qdest")

    engine = make_joinmarket_engine([
        {"round_id": 1, "status": "started", "taker": "jcs-000", "destination_address": "bcrt1qdest"},
        {"round_id": 2, "status": "started", "taker": "jcs-001", "destination_address": "bcrt1qother"},
    ])
    evidence = engine.store_engine_logs(str(tmp_path))
    assert evidence is not None

    labels = json.loads((tmp_path / "joinmarket_round_events.json").read_text(encoding="utf-8"))
    confirmed = {label["taker"]: label for label in labels if label["status"] == "confirmed"}
    assert set(confirmed) == {"jcs-000"}
    assert confirmed["jcs-000"]["destination_matches"] == [{"txid": "a" * 64, "block_height": 7}]
    assert evidence["positive_count"] == 1
    assert evidence["sources"] == ["joinmarket_round_events.json"]


def test_a_reused_destination_makes_labels_incomplete(tmp_path: Path) -> None:
    node_path = tmp_path / "btc-node"
    node_path.mkdir()
    write_block(str(node_path), 7, "a" * 64, "bcrt1qdest")
    write_block(str(node_path), 8, "b" * 64, "bcrt1qdest")

    engine = make_joinmarket_engine([
        {"round_id": 1, "status": "started", "taker": "jcs-000", "destination_address": "bcrt1qdest"},
    ])
    evidence = engine.store_engine_logs(str(tmp_path))

    label = json.loads((tmp_path / "joinmarket_round_events.json").read_text(encoding="utf-8"))[0]
    assert label["status"] == "ambiguous"
    assert label["destination_matches"] == [
        {"txid": "a" * 64, "block_height": 7},
        {"txid": "b" * 64, "block_height": 8},
    ]
    assert evidence["complete"] is False
    assert evidence["positive_count"] == 0


def test_rounds_without_a_mined_destination_stay_unconfirmed(tmp_path: Path) -> None:
    (tmp_path / "btc-node").mkdir()
    engine = make_joinmarket_engine([
        {"round_id": 1, "status": "started", "taker": "jcs-000", "destination_address": "bcrt1qdest"},
    ])
    evidence = engine.store_engine_logs(str(tmp_path))
    assert evidence is not None

    label = json.loads((tmp_path / "joinmarket_round_events.json").read_text(encoding="utf-8"))[0]
    assert label["status"] == "started"
    assert evidence["positive_count"] == 0
