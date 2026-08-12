"""Collection, reconciliation, and evidence for JoinMarket round events."""

from collections.abc import Iterable

from manager.engine.base.manifest import ProducerLabelEvidence
from manager.engine.joinmarket.exported_block_record import ExportedBlock, ExportedBlockRecord
from manager.engine.joinmarket.round_event_record import (
    EVENT_STATUS_AMBIGUOUS,
    RoundEvent,
    RoundEventRecord,
)


def collect_round_events(event_groups: Iterable[Iterable[RoundEvent]]) -> list[RoundEvent]:
    """Copy producer records once and assign stable global export identifiers."""
    return [
        RoundEventRecord.from_data(event).copy_with_export_round_id(export_round_id)
        for export_round_id, event in enumerate(
            (event for events in event_groups for event in events),
            start=1,
        )
    ]


def match_round_events_to_blocks(
    events: Iterable[RoundEvent],
    blocks: Iterable[ExportedBlock],
) -> list[RoundEvent]:
    """Reconcile export event records against the exported Bitcoin blocks."""
    labels_by_destination = {
        event.destination_address: event
        for event in (RoundEventRecord.from_data(raw_event) for raw_event in events)
        if event.destination_address is not None
    }
    for block in (ExportedBlockRecord.from_data(raw_block) for raw_block in blocks):
        block_height = block.height
        if block_height is None:
            raise ValueError("exported block height must be an integer")
        for transaction in block.transactions:
            txid = transaction.txid
            if txid is None:
                raise ValueError("exported transaction txid must be a non-empty string")
            for output in transaction.outputs:
                if (address := output.address) is not None:
                    event = labels_by_destination.get(address)
                    if event is not None:
                        event.add_destination_match(txid, block_height)
    return [
        event.to_data()
        for event in sorted(labels_by_destination.values(), key=lambda event: (event.export_round_id, event.taker))
    ]


def producer_label_evidence(
    labels: Iterable[RoundEvent],
    unlabelled_takers: list[str],
) -> ProducerLabelEvidence:
    """Build manifest evidence from reconciled records and known omissions."""
    records = [RoundEventRecord.from_data(label) for label in labels]
    ambiguous = [record for record in records if record.status == EVENT_STATUS_AMBIGUOUS]
    incomplete_reasons: list[str] = []
    if unlabelled_takers:
        incomplete_reasons.append(
            f"tumbler takers produce no per-round labels: {', '.join(sorted(unlabelled_takers))}"
        )
    if ambiguous:
        rounds = ", ".join(str(record.round_id if record.round_id is not None else "?") for record in ambiguous)
        incomplete_reasons.append(
            f"destination output matches multiple exported transactions for rounds: {rounds}"
        )
    positive_txids = {
        txid for record in records if (txid := record.confirmed_destination_txid()) is not None
    }
    return {
        "engine": "joinmarket",
        "complete": not incomplete_reasons,
        "reason": None if not incomplete_reasons else "; ".join(incomplete_reasons),
        "positive_rule": "exported transaction is the sole destination match for a reconciled JoinMarket round event",
        "positive_count": len(positive_txids),
        "sources": ["joinmarket_round_events.json"],
    }
