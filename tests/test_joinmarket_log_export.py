"""The published run must include the daemon log consumed by coinjoin-analysis."""

import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from manager.engine.joinmarket_engine import JoinmarketEngine


def make_log_export(tmp_path, monkeypatch, *, daemon_log=True):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("manager.engine.engine_base.sleep", lambda _: None)
    container = tmp_path / "container"
    (container / "logs").mkdir(parents=True)
    (container / "logs/nick.log").write_text("wallet ownership log\n", encoding="utf-8")
    if daemon_log:
        (container / "jmwalletd.log").write_text("daemon console log\n", encoding="utf-8")

    def download(_name, source, destination):
        source = container / Path(source).name
        target = Path(destination) / source.name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)

    engine = JoinmarketEngine(
        SimpleNamespace(run_id="joinmarket-log-export"),
        SimpleNamespace(download=download),
    )
    engine.node = SimpleNamespace(
        get_block_count=lambda: 0,
        get_block_hash=lambda height: str(height),
        get_block_info=lambda _hash: {"height": 0, "tx": []},
    )
    engine.clients = [SimpleNamespace(
        name="jcs-000",
        round_events=[],
        list_coins=lambda: [],
        list_unspent_coins=lambda: [],
        list_keys=lambda: [],
        get_history=lambda: [],
    )]
    return engine, tmp_path / "logs/joinmarket-log-export/coinjoin_emulator_data"


def test_joinmarket_archive_includes_daemon_wallet_logs_and_ground_truth(tmp_path, monkeypatch):
    engine, output = make_log_export(tmp_path, monkeypatch)

    engine.store_logs()

    daemon = "data/jcs-000/joinmarket/jmwalletd.log"
    wallet = "data/jcs-000/logs/nick.log"
    assert (output / daemon).read_text() == "daemon console log\n"
    assert (output / wallet).read_text() == "wallet ownership log\n"
    manifest = json.loads((output / "data/coinjoin_label_manifest.json").read_text())
    assert manifest["sources"][0]["path"] == "joinmarket_round_events.json"
    with zipfile.ZipFile(output / "emulation_logs.zip") as archive:
        assert archive.read(f"coinjoin_emulator_data/{daemon}") == b"daemon console log\n"
        assert archive.read(f"coinjoin_emulator_data/{wallet}") == b"wallet ownership log\n"


def test_missing_daemon_log_fails_export_instead_of_publishing_an_incomplete_archive(tmp_path, monkeypatch):
    engine, output = make_log_export(tmp_path, monkeypatch, daemon_log=False)

    with pytest.raises(FileNotFoundError, match="jmwalletd.log"):
        engine.store_logs()

    assert not (output / "emulation_logs.zip").exists()
