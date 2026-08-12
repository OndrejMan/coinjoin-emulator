"""Collection of the JoinMarket log artifacts."""

import os
import shutil

from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient


def store_orderbook_snapshots(
    data_path: str,
    client: OrderbookWatchClient | None,
) -> None:
    """Copy watcher snapshots into an artifact directory."""
    print(f"- storing {data_path}")
    ob_root = os.path.join(data_path, "orderbook")
    os.makedirs(ob_root, exist_ok=True)

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
        # Preserve the watcher directory structure while merging it into the artifact tree.
        for root, _, files in os.walk(src):
            print(f"- found {root}")
            rel = os.path.relpath(root, src)
            target_dir = os.path.join(dst, rel) if rel != "." else dst
            os.makedirs(target_dir, exist_ok=True)
            for filename in files:
                print(f"- found {filename}")
                target_path = os.path.join(target_dir, filename)
                shutil.copy2(os.path.join(root, filename), target_path)
        print(f"- stored orderbook snapshots for {client.name}")
    except Exception as error:
        print(f"- could not store orderbook snapshots for {client.name}: {error}")
