"""A round is confirmed by its destination output landing in a mined block."""

import pytest

from manager.engine.joinmarket.events import collect_round_events, match_round_events_to_blocks
from manager.engine.joinmarket.round_confirmation import (
    confirm_rounds_in_blocks,
    count_confirmed_rounds,
    mark_latest_started_round_failed,
)


class FakeNode:
    def __init__(self, blocks: list[list[dict[str, object]]]) -> None:
        self.blocks = blocks
        self.fetched: list[int] = []

    def get_block_count(self) -> int:
        return len(self.blocks) - 1

    def get_block_hash(self, height: int) -> str:
        return f"hash-{height}"

    def get_block_info(self, block_hash: str) -> dict[str, object]:
        height = int(block_hash.removeprefix("hash-"))
        self.fetched.append(height)
        return {"height": height, "tx": self.blocks[height]}


def started(taker: str, destination: str) -> dict[str, object]:
    return {"taker": taker, "status": "started", "destination_address": destination}


def paying(txid: str, *addresses: str) -> dict[str, object]:
    return {"txid": txid, "vout": [{"scriptPubKey": {"address": address}} for address in addresses]}


def test_a_mined_destination_confirms_the_round() -> None:
    event = started("jcs-000", "bcrt1a")
    node = FakeNode([[], [paying("coinbase-1")], [paying("cj-2", "bcrt1x", "bcrt1a")]])

    scanned = confirm_rounds_in_blocks([event], node, scanned_height=-1)

    assert scanned == 2
    assert event["status"] == "confirmed"
    assert event["destination_matches"] == [{"txid": "cj-2", "block_height": 2}]
    assert count_confirmed_rounds([event]) == 1


def test_live_and_export_paths_share_destination_matching() -> None:
    live_event = started("jcs-000", "bcrt1a")
    transaction = paying("cj-1", "bcrt1x", "bcrt1a")

    confirm_rounds_in_blocks([live_event], FakeNode([[], [transaction]]), scanned_height=-1)
    export_event = match_round_events_to_blocks(
        collect_round_events([[started("jcs-000", "bcrt1a")]]),
        [{"height": 1, "tx": [transaction]}],
    )[0]

    for field in ("status", "destination_matches", "match_source"):
        assert live_event[field] == export_event[field]


def test_only_blocks_above_the_scanned_height_are_fetched() -> None:
    node = FakeNode([[], [paying("coinbase-1")], [paying("coinbase-2")]])

    assert confirm_rounds_in_blocks([], node, scanned_height=1) == 2
    assert node.fetched == [2]


def test_a_shortened_chain_moves_the_scanned_height_back_to_the_tip() -> None:
    node = FakeNode([[], [paying("coinbase-1")]])

    assert confirm_rounds_in_blocks([], node, scanned_height=5) == 1
    assert node.fetched == []


def test_an_unmined_destination_stays_pending() -> None:
    event = started("jcs-000", "bcrt1a")
    node = FakeNode([[], [paying("cj-1", "bcrt1other")]])

    confirm_rounds_in_blocks([event], node, scanned_height=-1)

    assert event["status"] == "started"
    assert count_confirmed_rounds([event]) == 0


def test_a_live_scan_rejects_a_transaction_without_a_txid() -> None:
    event = started("jcs-000", "bcrt1a")
    malformed = {"vout": [{"scriptPubKey": {"address": "bcrt1a"}}]}

    with pytest.raises(ValueError, match="txid"):
        confirm_rounds_in_blocks([event], FakeNode([[], [malformed]]), scanned_height=-1)


def test_the_latest_started_attempt_of_the_taker_is_failed() -> None:
    older = started("jcs-000", "bcrt1a")
    other = started("jcs-001", "bcrt1b")
    newest = started("jcs-000", "bcrt1c")

    failed = mark_latest_started_round_failed([older, other, newest], "jcs-000", "timed out", stop_block=9)

    assert failed is newest
    assert newest == {**started("jcs-000", "bcrt1c"), "status": "failed", "failure_reason": "timed out", "stop_block": 9}
    assert older["status"] == "started"
    assert other["status"] == "started"


def test_failing_a_taker_without_a_pending_attempt_is_a_no_op() -> None:
    assert mark_latest_started_round_failed([], "jcs-000", "timed out", stop_block=1) is None
