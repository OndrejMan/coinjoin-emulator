"""Collection, reconciliation, and evidence for JoinMarket round events."""

from collections.abc import Iterable, Iterator

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


def reconcile_round_event_destinations(
    events: Iterable[RoundEvent],
    blocks: Iterable[tuple[int, ExportedBlock]],
) -> list[RoundEvent]:
    """Match event destinations to block outputs and mutate the matching events."""
    events_by_destination: dict[str, RoundEvent] = {}
    for event in events:
        destination = RoundEventRecord.from_data(event).destination_address
        if destination is not None:
            events_by_destination[destination] = event

    for block_height, raw_block in blocks:
        for transaction in ExportedBlockRecord.from_data(raw_block).transactions:
            txid = transaction.txid
            if txid is None:
                raise ValueError("exported transaction txid must be a non-empty string")
            for output in transaction.outputs:
                address = output.address
                matched_event = events_by_destination.get(address) if address is not None else None
                if matched_event is not None:
                    RoundEventRecord.from_data(matched_event).add_destination_match(txid, block_height)

    return list(events_by_destination.values())


def match_round_events_to_blocks(
    events: Iterable[RoundEvent],
    blocks: Iterable[ExportedBlock],
) -> list[RoundEvent]:
    """Reconcile export event records against the exported Bitcoin blocks."""
    def indexed_blocks() -> Iterator[tuple[int, ExportedBlock]]:
        for raw_block in blocks:
            block_height = ExportedBlockRecord.from_data(raw_block).height
            if block_height is None:
                raise ValueError("exported block height must be an integer")
            yield block_height, raw_block

    labels = reconcile_round_event_destinations(events, indexed_blocks())
    return [
        event.to_data()
        for event in sorted(
            (RoundEventRecord.from_data(label) for label in labels),
            key=lambda event: (event.export_round_id, event.taker),
        )
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
