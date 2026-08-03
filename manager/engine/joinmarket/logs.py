"""Collection of the JoinMarket log artifacts."""

import os
import shutil
from typing import TYPE_CHECKING

from manager.driver import Driver
from manager.engine.engine_base import EmulatorClient
from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient


class JoinMarketLogsMixin:
    """Copies client logs and orderbook snapshots into the run directory."""

    driver: Driver
    clients: list[EmulatorClient]
    obwatch_client: OrderbookWatchClient | None

    if TYPE_CHECKING:
        def store_round_events(self, data_path: str) -> dict[str, object]: ...

    def store_engine_logs(self, data_path: str) -> dict[str, object] | None:
        print("- storing engine-logs")
        self.store_orderbook_snapshots(data_path)
        return self.store_round_events(data_path)

    def store_orderbook_snapshots(self, data_path: str) -> None:
        # Store orderbook snapshots, grouped under data_path/orderbook/<client.name>
        print(f"- storing {data_path}")
        ob_root = os.path.join(data_path, "orderbook")
        os.makedirs(ob_root, exist_ok=True)
        client = self.obwatch_client

        # Check if orderbook watcher client exists
        if client is None:
            print("- no orderbook watcher client to store")
            return

        src = getattr(client, "snapshot_dir", None)
        if not src or not os.path.isdir(src):
            print(f"- no snapshots to store for {client.name}")
            return
        dst = os.path.join(ob_root, client.name)
        os.makedirs(dst, exist_ok=True)
        try:
            # Prefer copytree with dirs_exist_ok when possible to preserve structure
            # Copy content of src into dst (merge)
            for root, dirs, files in os.walk(src):
                print(f"- found {root}")
                rel = os.path.relpath(root, src)
                target_dir = os.path.join(dst, rel) if rel != "." else dst
                os.makedirs(target_dir, exist_ok=True)
                for f in files:
                    print(f"- found {f}")
                    shutil.copy2(os.path.join(root, f), os.path.join(target_dir, f))
            print(f"- stored orderbook snapshots for {client.name}")
        except Exception as e:
            print(f"- could not store orderbook snapshots for {client.name}: {e}")
