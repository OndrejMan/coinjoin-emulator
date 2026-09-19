"""The raw Bitcoin datadir is copied only while nothing can change it."""

import pytest

from manager.btc_datadir_snapshot import CHAIN_TIP_RACE_RETRIES, snapshot_btc_datadir


class RecordingDriver:
    """Records the snapshot protocol and unpacks a fake datadir on download."""

    def __init__(self, dest, failing_download=False, failing_pause=False):
        self.dest = dest
        self.failing_download = failing_download
        self.failing_pause = failing_pause
        self.calls = []
        self.copies = 0

    def pause(self, name):
        self.calls.append(("pause", name))
        if self.failing_pause:
            raise RuntimeError("pause status unknown")

    def unpause(self, name):
        self.calls.append(("unpause", name))

    def download(self, name, src_path, dst_path):
        self.calls.append(("download", name, src_path, dst_path))
        if self.failing_download:
            raise RuntimeError("archive unavailable")
        self.copies += 1
        copied = self.dest / "data"
        copied.mkdir(parents=True, exist_ok=True)
        (copied / f"copy-{self.copies}").write_text("blocks", encoding="utf-8")


class MovingTipNode:
    """A node whose chain tip advances after the given number of snapshots."""

    def __init__(self, heights, calls):
        self.heights = iter(heights)
        self.calls = calls

    def get_block_count(self):
        height = next(self.heights)
        self.calls.append(("height", height))
        return height

    def flush_state_to_disk(self):
        self.calls.append("flush")


def test_the_node_is_flushed_and_frozen_around_the_copy(tmp_path):
    driver = RecordingDriver(tmp_path)
    node = MovingTipNode([1200, 1200], driver.calls)

    height = snapshot_btc_datadir(node, driver, "btc-node", "/home/bitcoin/data/", str(tmp_path))

    assert height == 1200
    assert driver.calls == [
        ("height", 1200),
        "flush",
        ("pause", "btc-node"),
        ("download", "btc-node", "/home/bitcoin/data/", str(tmp_path)),
        ("unpause", "btc-node"),
        ("height", 1200),
    ]


def test_a_block_mined_between_flush_and_freeze_repeats_the_copy(tmp_path):
    driver = RecordingDriver(tmp_path)
    node = MovingTipNode([1200, 1201, 1201, 1201], driver.calls)

    assert snapshot_btc_datadir(node, driver, "btc-node", "/home/bitcoin/data/", str(tmp_path)) == 1201
    assert driver.calls.count("flush") == 2
    assert driver.calls.count(("pause", "btc-node")) == driver.calls.count(("unpause", "btc-node")) == 2
    # The earlier copy is discarded so the second one holds only files of a single snapshot.
    assert sorted(path.name for path in (tmp_path / "data").iterdir()) == ["copy-2"]


def test_a_tip_that_keeps_moving_fails_the_snapshot(tmp_path):
    driver = RecordingDriver(tmp_path)
    node = MovingTipNode([height for h in range(CHAIN_TIP_RACE_RETRIES) for height in (h, h + 1)], driver.calls)

    with pytest.raises(RuntimeError, match="kept moving"):
        snapshot_btc_datadir(node, driver, "btc-node", "/home/bitcoin/data/", str(tmp_path))

    assert driver.calls.count("flush") == CHAIN_TIP_RACE_RETRIES


def test_the_node_is_resumed_when_the_copy_fails(tmp_path):
    driver = RecordingDriver(tmp_path, failing_download=True)
    node = MovingTipNode([1200], driver.calls)

    with pytest.raises(RuntimeError, match="archive unavailable"):
        snapshot_btc_datadir(node, driver, "btc-node", "/home/bitcoin/data/", str(tmp_path))

    assert driver.calls[-1] == ("unpause", "btc-node")


def test_the_node_is_resumed_when_the_pause_result_is_unknown(tmp_path):
    driver = RecordingDriver(tmp_path, failing_pause=True)
    node = MovingTipNode([1200], driver.calls)

    with pytest.raises(RuntimeError, match="pause status unknown"):
        snapshot_btc_datadir(node, driver, "btc-node", "/home/bitcoin/data/", str(tmp_path))

    assert driver.calls[-2:] == [("pause", "btc-node"), ("unpause", "btc-node")]
