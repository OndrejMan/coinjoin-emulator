import json
from pathlib import Path
from typing import cast

from manager.btc_node import BtcNode
from manager.engine.base.protocols import EmulatorClient
from manager.engine.joinmarket_engine import JoinmarketEngine


class EventClient:
    def __init__(
        self,
        name: str,
        round_events: list[dict[str, object]],
        tumbler_options: dict[str, object] | None = None,
    ) -> None:
        self.name = name
        self.round_events = round_events
        self.tumbler_options = tumbler_options


class EventHarness(JoinmarketEngine):
    def __init__(self, *clients: EventClient) -> None:
        self.clients = [cast(EmulatorClient, client) for client in clients]
        self.node: BtcNode | None = None
        self.current_round = 0
        self._round_scan_height = -1


class EventNode:
    def __init__(self, blocks: list[dict[str, object]]) -> None:
        self.blocks = blocks

    def get_block_count(self) -> int:
        return len(self.blocks) - 1

    def get_block_hash(self, height: int) -> str:
        return str(height)

    def get_block_info(self, block_hash: str) -> dict[str, object]:
        return self.blocks[int(block_hash)]


def write_block(node_path: Path, height: int, txid: str, address: str) -> None:
    node_path.mkdir(exist_ok=True)
    (node_path / f"block_{height}.json").write_text(
        json.dumps(
            {
                "height": height,
                "tx": [{"txid": txid, "vout": [{"scriptPubKey": {"address": address}}]}],
            }
        ),
        encoding="utf-8",
    )


class TestCollectRoundEvents:
    def test_events_are_collected_from_every_client(self) -> None:
        harness = EventHarness(
            EventClient("jcs-000", [{"round_id": 1}]),
            EventClient("jcs-001", [{"round_id": 2}]),
        )

        assert harness.collect_round_events() == [
            {"round_id": 1, "export_round_id": 1},
            {"round_id": 2, "export_round_id": 2},
        ]

    def test_collected_events_are_copies_of_the_client_records(self) -> None:
        client = EventClient("jcs-000", [{"round_id": 1, "status": "started"}])
        harness = EventHarness(client)

        harness.collect_round_events()[0]["status"] = "confirmed"

        assert client.round_events[0]["status"] == "started"


class TestJoinMarketRoundEvents:
    def test_live_round_count_advances_only_for_mined_destination(self) -> None:
        event = {
            "round_id": 1,
            "status": "started",
            "destination_address": "destination-address",
        }
        client = EventClient("jcs-000", [event])
        harness = EventHarness(client)
        harness.node = cast(
            BtcNode,
            EventNode(
                [
                    {"tx": []},
                    {
                        "tx": [
                            {
                                "txid": "coinjoin-txid",
                                "vout": [
                                    {"scriptPubKey": {"address": "destination-address"}}
                                ],
                            }
                        ]
                    },
                ]
            ),
        )

        assert harness.confirm_started_rounds() == 1
        assert event == {
            "round_id": 1,
            "status": "confirmed",
            "destination_address": "destination-address",
            "destination_matches": [{"txid": "coinjoin-txid", "block_height": 1}],
            "match_source": "destination_output",
        }
        assert client.round_events == [event]

    def test_live_round_count_ignores_rpc_start_without_chain_match(self) -> None:
        event = {"round_id": 1, "status": "started", "destination_address": "unmined"}
        harness = EventHarness(EventClient("jcs-000", [event]))
        harness.node = cast(BtcNode, EventNode([{"tx": []}]))

        assert harness.confirm_started_rounds() == 0
        assert event["status"] == "started"

    def test_live_round_count_ignores_a_malformed_rpc_txid(self) -> None:
        event = {"round_id": 1, "status": "started", "destination_address": "destination-address"}
        harness = EventHarness(EventClient("jcs-000", [event]))
        harness.node = cast(
            BtcNode,
            EventNode(
                [
                    {"tx": []},
                    {
                        "tx": [
                            {
                                "txid": 42,
                                "vout": [{"scriptPubKey": {"address": "destination-address"}}],
                            }
                        ]
                    },
                ]
            ),
        )

        assert harness.confirm_started_rounds() == 0
        assert event["status"] == "started"

    def test_round_event_is_matched_to_the_block_paying_its_destination(self, tmp_path: Path) -> None:
        write_block(tmp_path / "btc-node", 7, "coinjoin-txid", "destination-address")
        event = {
            "round_id": 2,
            "status": "started",
            "taker": "jcs-002",
            "destination_address": "destination-address",
        }
        harness = EventHarness(EventClient("jcs-002", [event]))

        labels = harness.match_joinmarket_rounds_to_blocks(str(tmp_path))

        assert labels == [
            {
                "round_id": 2,
                "export_round_id": 1,
                "status": "confirmed",
                "taker": "jcs-002",
                "destination_address": "destination-address",
                "destination_matches": [{"txid": "coinjoin-txid", "block_height": 7}],
                "match_source": "destination_output",
            }
        ]
        assert event["status"] == "started"
        assert "destination_matches" not in event

    def test_reconciliation_marks_reused_destinations_as_ambiguous(self, tmp_path: Path) -> None:
        node_path = tmp_path / "btc-node"
        for height, txid in ((3, "first-match"), (4, "second-match")):
            write_block(node_path, height, txid, "reused-destination")
        harness = EventHarness(
            EventClient("jcs-000", [{"round_id": 4, "destination_address": "reused-destination"}])
        )

        label = harness.match_joinmarket_rounds_to_blocks(str(tmp_path))[0]

        assert label["status"] == "ambiguous"
        assert label["destination_matches"] == [
            {"txid": "first-match", "block_height": 3},
            {"txid": "second-match", "block_height": 4},
        ]

    def test_events_are_returned_unmatched_when_no_blocks_were_exported(self, tmp_path: Path) -> None:
        harness = EventHarness(
            EventClient("jcs-000", [{"round_id": 1, "destination_address": "unmined-destination"}])
        )

        labels = harness.match_joinmarket_rounds_to_blocks(str(tmp_path))

        assert labels == [
            {
                "round_id": 1,
                "export_round_id": 1,
                "destination_address": "unmined-destination",
            }
        ]

    def test_export_ids_are_unique_across_parallel_takers(self, tmp_path: Path) -> None:
        first = {
            "round_id": 1,
            "taker": "jcs-000",
            "destination_address": "first-destination",
        }
        second = {
            "round_id": 1,
            "taker": "jcs-001",
            "destination_address": "second-destination",
        }
        harness = EventHarness(
            EventClient("jcs-000", [first]),
            EventClient("jcs-001", [second]),
        )

        labels = harness.match_joinmarket_rounds_to_blocks(str(tmp_path))

        assert [(label["round_id"], label["export_round_id"]) for label in labels] == [
            (1, 1),
            (1, 2),
        ]
        assert first["round_id"] == second["round_id"] == 1

    def test_events_without_a_destination_are_dropped(self, tmp_path: Path) -> None:
        harness = EventHarness(EventClient("jcs-000", [{"round_id": 1, "status": "failed"}]))

        assert harness.match_joinmarket_rounds_to_blocks(str(tmp_path)) == []


class TestStoreRoundEvents:
    def test_stored_evidence_counts_the_confirmed_transactions(self, tmp_path: Path) -> None:
        write_block(tmp_path / "btc-node", 7, "coinjoin-txid", "destination-address")
        harness = EventHarness(
            EventClient("jcs-000", [{"round_id": 1, "destination_address": "destination-address"}])
        )

        evidence = harness.store_round_events(str(tmp_path))

        assert evidence["engine"] == "joinmarket"
        assert evidence["complete"] is True
        assert evidence["positive_count"] == 1
        assert evidence["sources"] == ["joinmarket_round_events.json"]

    def test_stored_file_holds_the_reconciled_labels(self, tmp_path: Path) -> None:
        write_block(tmp_path / "btc-node", 7, "coinjoin-txid", "destination-address")
        harness = EventHarness(
            EventClient("jcs-000", [{"round_id": 1, "destination_address": "destination-address"}])
        )

        harness.store_round_events(str(tmp_path))

        stored = json.loads((tmp_path / "joinmarket_round_events.json").read_text(encoding="utf-8"))
        assert stored[0]["destination_matches"] == [{"txid": "coinjoin-txid", "block_height": 7}]
        assert stored[0]["status"] == "confirmed"

    def test_ambiguous_destinations_make_the_evidence_incomplete(self, tmp_path: Path) -> None:
        for height, txid in ((7, "first-match"), (8, "second-match")):
            write_block(tmp_path / "btc-node", height, txid, "reused-destination")
        harness = EventHarness(
            EventClient("jcs-000", [{"round_id": 1, "destination_address": "reused-destination"}])
        )

        evidence = harness.store_round_events(str(tmp_path))

        assert evidence["complete"] is False
        assert evidence["positive_count"] == 0
        assert "multiple exported transactions" in str(evidence["reason"])

    def test_a_tumbler_without_labels_marks_the_evidence_incomplete(self, tmp_path: Path) -> None:
        harness = EventHarness(
            EventClient("jcs-000", [], tumbler_options={"addrcount": 3}),
            EventClient("jcs-001", [{"round_id": 1, "destination_address": "bcrt1qdest"}]),
        )

        evidence = harness.store_round_events(str(tmp_path))

        assert evidence["complete"] is False
        assert "jcs-000" in str(evidence["reason"])

    def test_a_tumbler_that_recorded_labels_keeps_the_evidence_complete(self, tmp_path: Path) -> None:
        harness = EventHarness(
            EventClient(
                "jcs-000",
                [{"round_id": 1, "destination_address": "bcrt1qdest"}],
                tumbler_options={"addrcount": 3},
            )
        )

        assert harness.store_round_events(str(tmp_path))["complete"] is True

    def test_unconfirmed_rounds_are_not_counted_as_positives(self, tmp_path: Path) -> None:
        harness = EventHarness(
            EventClient("jcs-000", [{"round_id": 1, "destination_address": "unmined-destination"}])
        )

        assert harness.store_round_events(str(tmp_path))["positive_count"] == 0
