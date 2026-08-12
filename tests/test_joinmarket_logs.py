from pathlib import Path
from typing import cast

from manager.engine.joinmarket.logs import store_orderbook_snapshots
from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient


class SnapshotClient:
    def __init__(self, name: str, snapshot_dir: Path) -> None:
        self.name = name
        self.snapshot_dir = str(snapshot_dir)


def test_store_orderbook_snapshots_copies_files(tmp_path: Path) -> None:
    source = tmp_path / "watcher"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "first.json").write_text("first", encoding="utf-8")
    (nested / "second.json").write_text("second", encoding="utf-8")
    client = SnapshotClient("obwatch", source)
    data_path = tmp_path / "data"

    store_orderbook_snapshots(
        str(data_path),
        cast(OrderbookWatchClient, client),
    )

    assert (data_path / "orderbook" / "obwatch" / "first.json").read_text(encoding="utf-8") == "first"
    assert (
        data_path / "orderbook" / "obwatch" / "nested" / "second.json"
    ).read_text(encoding="utf-8") == "second"
