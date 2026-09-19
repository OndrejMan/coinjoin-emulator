"""Copy a consistent Bitcoin Core datadir out of the running node container."""

import os
import shutil
from typing import Protocol

CHAIN_TIP_RACE_RETRIES = 3


class DatadirNode(Protocol):
    """The node RPCs the snapshot needs."""

    def get_block_count(self) -> int:
        """Return the height of the chain tip."""

    def flush_state_to_disk(self) -> None:
        """Write the in-memory block index and chainstate to the datadir."""


class DatadirDriver(Protocol):
    """The container operations the snapshot needs."""

    def pause(self, name: str) -> None:
        """Freeze every process of the container."""

    def unpause(self, name: str) -> None:
        """Resume the frozen container."""

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        """Unpack the container path into the local directory."""


def snapshot_btc_datadir(
    node: DatadirNode,
    driver: DatadirDriver,
    name: str,
    src_path: str,
    dest_path: str,
) -> int:
    """Archive the node's datadir with nothing writing to it; return the snapshot height."""
    for attempt in range(1, CHAIN_TIP_RACE_RETRIES + 1):
        height = node.get_block_count()
        node.flush_state_to_disk()
        try:
            driver.pause(name)
            driver.download(name, src_path, dest_path)
        finally:
            driver.unpause(name)
        if node.get_block_count() == height:
            return height
        print(f"- a block was mined while {name}:{src_path} was flushed; copying it again ({attempt}/{CHAIN_TIP_RACE_RETRIES})")
        _discard_copy(src_path, dest_path)
    raise RuntimeError(f"the chain tip kept moving during {CHAIN_TIP_RACE_RETRIES} copies of {name}:{src_path}")


def _discard_copy(src_path: str, dest_path: str) -> None:
    """Remove the unpacked archive so a repeated copy leaves no file from the earlier one."""
    copied = os.path.join(dest_path, os.path.basename(src_path.rstrip("/")))
    shutil.rmtree(copied, ignore_errors=True)
