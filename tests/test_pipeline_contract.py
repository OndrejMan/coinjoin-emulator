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

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from manager.engine.configuration import (  # noqa: E402
    JoinMarketConfig,
    JoinMarketRole,
    ScenarioConfig,
    WalletConfig,
)
from manager.engine.engine_base import EngineBase, write_producer_label_manifest  # noqa: E402
from manager.engine.joinmarket_engine import JoinmarketEngine  # noqa: E402


def load_entrypoint():
    """Import manager.py, which shares its name with the manager package."""
    spec = importlib.util.spec_from_file_location("manager_entrypoint", PROJECT_ROOT / "manager.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeNode:
    def __init__(self, blocks=2):
        self.blocks = blocks

    def get_block_count(self):
        return self.blocks

    def get_block_hash(self, height):
        return f"hash-{height}"

    def get_block_info(self, block_hash):
        return {"hash": block_hash, "height": 1}


class RecordingEngine(EngineBase):
    """Minimal concrete engine: everything the artifact layout needs, nothing else."""

    def default_scenario(self):
        return ScenarioConfig(
            name="scenario",
            rounds=1,
            blocks=0,
            default_version="v",
            wallets=[WalletConfig(funds=[1000])],
        )

    def store_engine_logs(self, data_path):
        with open(os.path.join(data_path, "engine.json"), "w", encoding="utf-8") as stream:
            json.dump({"engine": "recording"}, stream)
        return None


def make_engine(run_id=None, no_logs=False):
    args = types.SimpleNamespace(command="run", scenario=None, run_id=run_id, no_logs=no_logs)
    engine = RecordingEngine(args, None, "/src")
    engine.node = FakeNode()
    engine.clients = []
    return engine


# --- run IDs ---------------------------------------------------------------

@pytest.mark.parametrize("value", ["run-1", "2026-08-03_scenario", "a", "a.b_c-d"])
def test_run_id_accepts_safe_names(value):
    assert load_entrypoint().run_id(value) == value


@pytest.mark.parametrize("value", ["../escape", "-leading", "trailing-", "a/b", "a" * 64, "a..b"])
def test_run_id_rejects_unsafe_names(value):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        load_entrypoint().run_id(value)


def test_log_run_path_uses_the_requested_run_id():
    assert make_engine(run_id="pinned").log_run_path() == "./logs/pinned"


def test_log_run_path_falls_back_to_timestamp_and_scenario_name():
    path = make_engine().log_run_path()
    assert path.startswith("./logs/")
    assert path.endswith("_scenario")


def test_a_joinmarket_scenario_is_json_serialisable() -> None:
    scenario = ScenarioConfig(
        name="joinmarket",
        rounds=1,
        blocks=0,
        default_version="joinmarket",
        wallets=[
            WalletConfig(
                funds=[1000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            )
        ],
    )

    stored = json.loads(json.dumps(scenario.to_dict()))

    assert stored["wallets"][0]["joinmarket"]["role"] == "maker"


# --- controller markers ----------------------------------------------------

def test_controller_marker_is_written_for_the_matching_outcome(tmp_path):
    entrypoint = load_entrypoint()
    done = tmp_path / "nested" / "done.marker"
    failed = tmp_path / "nested" / "failed.marker"
    entrypoint.args = types.SimpleNamespace(
        controller_done_marker=str(done), controller_failed_marker=str(failed)
    )

    assert entrypoint.finalize_controller_marker(0) == 0
    assert done.exists() and not failed.exists()

    done.unlink()
    assert entrypoint.finalize_controller_marker(1) == 1
    assert failed.exists() and not done.exists()


def test_controller_markers_are_optional(tmp_path):
    entrypoint = load_entrypoint()
    entrypoint.args = types.SimpleNamespace(controller_done_marker="", controller_failed_marker="")
    assert entrypoint.finalize_controller_marker(0) == 0
    assert list(tmp_path.iterdir()) == []


# --- artifact layout -------------------------------------------------------

def test_store_logs_writes_the_emulator_artifact_layout(tmp_path, monkeypatch):
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


def test_run_refuses_to_overwrite_an_existing_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine = make_engine(run_id="my-run")
    engine.ensure_log_run_path_available()
    engine.store_logs()

    with pytest.raises(RuntimeError, match="already exists"):
        engine.ensure_log_run_path_available()


def test_a_prepared_run_directory_without_artifacts_is_accepted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs" / "my-run").mkdir(parents=True)
    (tmp_path / "logs" / "my-run" / "host_manifest.json").write_text("{}", encoding="utf-8")

    make_engine(run_id="my-run").ensure_log_run_path_available()


# --- producer-label manifest ----------------------------------------------

def test_manifest_records_sources_with_their_digest(tmp_path):
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


def test_manifest_is_incomplete_without_evidence(tmp_path):
    write_producer_label_manifest(str(tmp_path), None)
    manifest = json.loads((tmp_path / "coinjoin_label_manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["reason"]


def test_manifest_rejects_sources_outside_the_data_directory(tmp_path):
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

def make_joinmarket_engine(round_events):
    engine = object.__new__(JoinmarketEngine)
    engine.clients = [types.SimpleNamespace(round_events=round_events)]
    engine.obwatch_client = None
    return engine


def write_block(node_path, height, txid, address):
    with open(os.path.join(node_path, f"block_{height}.json"), "w", encoding="utf-8") as stream:
        json.dump(
            {"height": height, "tx": [{"txid": txid, "vout": [{"scriptPubKey": {"address": address}}]}]},
            stream,
        )


def test_round_events_are_matched_to_the_exported_blocks(tmp_path):
    node_path = tmp_path / "btc-node"
    node_path.mkdir()
    write_block(str(node_path), 7, "a" * 64, "bcrt1qdest")

    engine = make_joinmarket_engine([
        {"round_id": 1, "status": "started", "taker": "jcs-000", "destination_address": "bcrt1qdest"},
        {"round_id": 2, "status": "started", "taker": "jcs-001", "destination_address": "bcrt1qother"},
    ])
    evidence = engine.store_engine_logs(str(tmp_path))

    labels = json.loads((tmp_path / "joinmarket_round_events.json").read_text(encoding="utf-8"))
    confirmed = {label["taker"]: label for label in labels if label["status"] == "confirmed"}
    assert set(confirmed) == {"jcs-000"}
    assert confirmed["jcs-000"]["destination_matches"] == [{"txid": "a" * 64, "block_height": 7}]
    assert evidence["positive_count"] == 1
    assert evidence["sources"] == ["joinmarket_round_events.json"]


def test_a_reused_destination_makes_labels_incomplete(tmp_path):
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


def test_rounds_without_a_mined_destination_stay_unconfirmed(tmp_path):
    (tmp_path / "btc-node").mkdir()
    engine = make_joinmarket_engine([
        {"round_id": 1, "status": "started", "taker": "jcs-000", "destination_address": "bcrt1qdest"},
    ])
    evidence = engine.store_engine_logs(str(tmp_path))

    label = json.loads((tmp_path / "joinmarket_round_events.json").read_text(encoding="utf-8"))[0]
    assert label["status"] == "started"
    assert evidence["positive_count"] == 0
