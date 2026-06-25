import json
from pathlib import Path
from typing import cast

from manager.btc_node import BtcNode
from manager.engine.joinmarket.events import JoinMarketRoundEventsMixin


class EventNode:
    def get_block_count(self) -> int:
        return 6

    def get_block_hash(self, height: int) -> str:
        return f"block-{height}"

    def get_block_info(self, block_hash: str) -> dict[str, object]:
        height = int(block_hash.removeprefix("block-"))
        return {
            "height": height,
            "tx": [
                {
                    "txid": f"tx-{height}",
                    "vout": [
                        {
                            "scriptPubKey": {
                                "addresses": ["destination-from-node"],
                            },
                        }
                    ],
                }
            ],
        }


class EventHarness(JoinMarketRoundEventsMixin):
    def __init__(self) -> None:
        self.node = cast(BtcNode | None, EventNode())
        self.joinmarket_round_events: list[dict[str, object]] = []
        self.current_block = 2
        self.current_round = 0


class TestJoinMarketRoundEvents:
    def test_round_events_are_matched_to_exported_block_destination_outputs(self, tmp_path: Path) -> None:
        node_path = tmp_path / "btc-node"
        node_path.mkdir()
        (node_path / "block_7.json").write_text(
            json.dumps(
                {
                    "height": 7,
                    "tx": [
                        {
                            "txid": "coinjoin-txid",
                            "vout": [
                                {
                                    "scriptPubKey": {
                                        "address": "destination-address",
                                    },
                                },
                            ],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        harness = EventHarness()
        harness.joinmarket_round_events = [
            {
                "round_id": 2,
                "status": "started",
                "taker": "jcs-002",
                "destination_address": "destination-address",
            },
        ]

        labels = harness.match_joinmarket_rounds_to_blocks(str(tmp_path))

        assert labels == [
            {
                "round_id": 2,
                "status": "started",
                "taker": "jcs-002",
                "destination_address": "destination-address",
                "txid": "coinjoin-txid",
                "block_height": 7,
                "match_source": "destination_output",
            }
        ]

    def test_round_events_confirm_started_round_from_live_node_lookup(self) -> None:
        harness = EventHarness()
        harness.joinmarket_round_events = [
            {
                "round_id": 1,
                "status": "started",
                "taker": "jcs-001",
                "destination_address": "destination-from-node",
                "start_chain_height": 5,
            }
        ]

        confirmed = harness.confirm_started_rounds()

        assert confirmed == 1
        assert harness.current_round == 1
        assert harness.joinmarket_round_events[0]["status"] == "confirmed"
        assert harness.joinmarket_round_events[0]["txid"] == "tx-5"
        assert harness.joinmarket_round_events[0]["block_height"] == 5
        assert harness.joinmarket_round_events[0]["confirmed_block"] == 2
