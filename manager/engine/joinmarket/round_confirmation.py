"""Confirm in-run JoinMarket round attempts against blocks mined on the node.

A taker's RPC start is only an attempt: jmwalletd reports it finished as soon as
the transaction is broadcast, and a failed negotiation never broadcasts at all.
A round counts once the unique destination address generated for the attempt
appears in a mined block.
"""

from collections.abc import Iterable
from typing import Protocol

from manager.engine.joinmarket.events import reconcile_round_event_destinations
from manager.engine.joinmarket.round_event_record import (
    EVENT_STATUS_CONFIRMED,
    EVENT_STATUS_FAILED,
    EVENT_STATUS_STARTED,
    RoundEvent,
)


class BlockSource(Protocol):
    """The node RPCs needed to walk mined blocks with their transactions."""

    def get_block_count(self) -> int:
        """Return the height of the chain tip."""

    def get_block_hash(self, height: int) -> str:
        """Return the hash of the block at ``height``."""

    def get_block_info(self, block_hash: str) -> dict[str, object]:
        """Return ``getblock`` verbosity-2 data, transactions included."""


def confirm_rounds_in_blocks(events: Iterable[RoundEvent], node: BlockSource, scanned_height: int) -> int:
    """Match pending destinations in blocks above ``scanned_height``; return the tip that was scanned."""
    tip = node.get_block_count()
    pending = (event for event in events if event.get("status") == EVENT_STATUS_STARTED)
    blocks = (
        (height, node.get_block_info(node.get_block_hash(height)))
        for height in range(scanned_height + 1, tip + 1)
    )
    reconcile_round_event_destinations(pending, blocks)
    return tip


def count_confirmed_rounds(events: Iterable[RoundEvent]) -> int:
    """Rounds whose destination was found in exactly one mined transaction."""
    return sum(1 for event in events if event.get("status") == EVENT_STATUS_CONFIRMED)


def mark_latest_started_round_failed(
    events: list[RoundEvent],
    taker: str,
    reason: str,
    stop_block: int,
) -> RoundEvent | None:
    """Close the taker's most recent pending attempt as failed; return it, if any."""
    for event in reversed(events):
        if event.get("status") == EVENT_STATUS_STARTED and event.get("taker") == taker:
            event["status"] = EVENT_STATUS_FAILED
            event["failure_reason"] = reason
            event["stop_block"] = stop_block
            return event
    return None
