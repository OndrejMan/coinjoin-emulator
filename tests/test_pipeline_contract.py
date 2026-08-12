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
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from manager.engine.configuration import ScenarioConfig, WalletConfig  # noqa: E402
from manager.engine.engine_base import EngineBase  # noqa: E402


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
