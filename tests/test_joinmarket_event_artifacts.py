"""Focused unit coverage for the JoinMarket round-event export artifact."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from manager.engine.joinmarket.events import (
    collect_round_events,
    match_round_events_to_blocks,
    producer_label_evidence,
)
from manager.engine.joinmarket.exported_block_record import ExportedBlockRecord
from manager.engine.joinmarket.round_event_record import RoundEvent, RoundEventRecord
from manager.engine.joinmarket.script_pub_key_record import ScriptPubKeyRecord
from manager.engine.joinmarket_engine import JoinmarketEngine


def exported_block(height: int, txid: str, script_pub_key: dict[str, object]) -> dict[str, object]:
    """Build one minimal exported block with one transaction output."""
    return {
        "height": height,
        "tx": [{"txid": txid, "vout": [{"scriptPubKey": script_pub_key}]}],
    }


def test_event_is_copied_reconciled_and_exported_as_evidence() -> None:
    source = {"round_id": 1, "taker": "jcs-000", "destination_address": "bcrt1qdestination"}

    labels = match_round_events_to_blocks(
        collect_round_events([[source]]),
        [exported_block(7, "a" * 64, {"address": "bcrt1qdestination"})],
    )

    assert source == {"round_id": 1, "taker": "jcs-000", "destination_address": "bcrt1qdestination"}
    assert labels == [
        {
            "round_id": 1,
            "export_round_id": 1,
            "taker": "jcs-000",
            "destination_address": "bcrt1qdestination",
            "destination_matches": [{"txid": "a" * 64, "block_height": 7}],
            "status": "confirmed",
            "match_source": "destination_output",
        }
    ]
    assert producer_label_evidence(labels, []) == {
        "engine": "joinmarket",
        "complete": True,
        "reason": None,
        "positive_rule": "exported transaction is the sole destination match for a reconciled JoinMarket round event",
        "positive_count": 1,
        "sources": ["joinmarket_round_events.json"],
    }


def test_multiple_destination_matches_are_not_positive() -> None:
    labels = match_round_events_to_blocks(
        collect_round_events([[{"round_id": 1, "destination_address": "reused-address"}]]),
        [
            exported_block(3, "a" * 64, {"address": "reused-address"}),
            exported_block(4, "b" * 64, {"address": "reused-address"}),
        ],
    )

    assert labels[0]["status"] == "multiple_matches"
    assert producer_label_evidence(labels, []) == {
        "engine": "joinmarket",
        "complete": False,
        "reason": "destination output matches multiple exported transactions for rounds: 1",
        "positive_rule": "exported transaction is the sole destination match for a reconciled JoinMarket round event",
        "positive_count": 0,
        "sources": ["joinmarket_round_events.json"],
    }


def test_record_views_reject_invalid_serialized_values() -> None:
    assert ExportedBlockRecord.from_data({"height": "7"}).height is None
    assert RoundEventRecord.from_data({"round_id": "1"}).round_id is None
    assert ScriptPubKeyRecord.from_data({"address": 1}).address is None


def test_export_round_id_is_mandatory_and_an_integer() -> None:
    with pytest.raises(KeyError):
        RoundEventRecord.from_data({}).export_round_id
    with pytest.raises(ValueError, match="export_round_id must be an integer"):
        RoundEventRecord.from_data({"export_round_id": "1"}).export_round_id


def test_events_without_destinations_are_dropped_and_export_order_is_stable() -> None:
    first = {"round_id": 1, "destination_address": "first"}
    second = {"round_id": 1, "destination_address": "second"}
    labels = match_round_events_to_blocks(
        collect_round_events([[{"round_id": 99, "status": "failed"}, first], [second]]),
        [],
    )

    assert [(label["round_id"], label["export_round_id"]) for label in labels] == [(1, 2), (1, 3)]
    assert first == {"round_id": 1, "destination_address": "first"}
    assert second == {"round_id": 1, "destination_address": "second"}


@pytest.mark.parametrize("match_count", [0, 1, 2])
def test_rounds_sharing_a_destination_keep_their_status_and_matches(match_count: int) -> None:
    events = collect_round_events([
        [{"round_id": 1, "destination_address": "reused-destination"}],
        [{"round_id": 1, "destination_address": "reused-destination"}],
    ])

    blocks = [
        exported_block(height, f"match-{height}", {"address": "reused-destination"})
        for height in range(match_count)
    ]
    labels = match_round_events_to_blocks(events, blocks)

    assert [label["status"] for label in labels] == ["duplicate_destination", "duplicate_destination"]
    assert [label["export_round_id"] for label in labels] == [1, 2]
    assert all("duplicate_destination" not in label for label in labels)
    evidence = producer_label_evidence(labels, [])
    assert evidence["complete"] is False
    assert evidence["positive_count"] == 0
    assert "shared by several rounds: 1, 1" in str(evidence["reason"])
    assert all(label["destination_matches"] == [
        {"txid": f"match-{height}", "block_height": height}
        for height in range(match_count)
    ] for label in labels)
    expected = json.loads(json.dumps(labels))
    assert match_round_events_to_blocks(labels, blocks) == expected


def test_duplicate_destination_status_survives_later_matching_without_the_other_round() -> None:
    event: RoundEvent = {"status": "duplicate_destination"}
    record = RoundEventRecord.from_data(event)

    record.add_destination_match("first", 1)
    record.add_destination_match("second", 2)

    assert record.status == "duplicate_destination"
    assert record.confirmed_destination_txid() is None
    assert event["destination_matches"] == [
        {"txid": "first", "block_height": 1},
        {"txid": "second", "block_height": 2},
    ]
    assert event["match_source"] == "destination_output"


def test_reconciliation_is_idempotent_and_tolerates_empty_transaction_lists() -> None:
    labels = match_round_events_to_blocks(
        collect_round_events([[{"round_id": 1, "destination_address": "destination"}]]),
        [
            {"height": 1, "tx": []},
            exported_block(3, "a" * 64, {"address": "destination"}),
            exported_block(3, "a" * 64, {"address": "destination"}),
        ],
    )

    assert labels[0]["destination_matches"] == [{"txid": "a" * 64, "block_height": 3}]
    assert labels[0]["status"] == "confirmed"


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ({"height": "2", "tx": []}, "height"),
        ({"height": 2, "tx": [{"txid": 42, "vout": []}]}, "txid"),
    ],
)
def test_reconciliation_rejects_malformed_export_data(block: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        match_round_events_to_blocks(collect_round_events([]), [block])


def test_confirmed_destination_txid_requires_one_well_formed_match() -> None:
    assert (
        RoundEventRecord.from_data({"status": "confirmed", "destination_matches": []}).confirmed_destination_txid()
        is None
    )
    assert (
        RoundEventRecord.from_data(
            {"status": "multiple_matches", "destination_matches": [{"txid": "a"}]}
        ).confirmed_destination_txid()
        is None
    )
    assert (
        RoundEventRecord.from_data(
            {"status": "confirmed", "destination_matches": [{"txid": 1, "block_height": 7}]}
        ).confirmed_destination_txid()
        is None
    )
    assert (
        RoundEventRecord.from_data(
            {"status": "confirmed", "destination_matches": [{"txid": "a", "block_height": 7}]}
        ).confirmed_destination_txid()
        == "a"
    )


def test_add_destination_match_discards_malformed_existing_matches() -> None:
    event: RoundEvent = {"destination_matches": [{"txid": 1, "block_height": "7"}]}

    RoundEventRecord.from_data(event).add_destination_match("a" * 64, 7)

    assert event["destination_matches"] == [{"txid": "a" * 64, "block_height": 7}]


def test_unlabelled_takers_make_evidence_incomplete() -> None:
    evidence = producer_label_evidence([], ["jcs-000"])

    assert evidence["complete"] is False
    assert evidence["positive_count"] == 0
    assert evidence["reason"] == "tumbler takers produce no per-round labels: jcs-000"


def test_engine_reads_exported_block_files_and_accepts_a_missing_node_directory(tmp_path: Path) -> None:
    engine = object.__new__(JoinmarketEngine)
    engine.clients = [SimpleNamespace(round_events=[{"round_id": 1, "destination_address": "destination"}])]

    assert engine.match_joinmarket_rounds_to_blocks(str(tmp_path)) == [
        {"round_id": 1, "export_round_id": 1, "destination_address": "destination"}
    ]

    node_path = tmp_path / "btc-node"
    node_path.mkdir()
    (node_path / "block_7.json").write_text(
        json.dumps(exported_block(7, "a" * 64, {"address": "destination"})),
        encoding="utf-8",
    )
    (node_path / "not-a-block.json").write_text("{}", encoding="utf-8")

    labels = engine.match_joinmarket_rounds_to_blocks(str(tmp_path))

    assert labels[0]["destination_matches"] == [{"txid": "a" * 64, "block_height": 7}]
