"""Producer-owned round records and their reconciliation with the chain."""

import json
import os
from typing import TYPE_CHECKING, cast

from manager.engine.base.protocols import EmulatorClient


class JoinMarketRoundEventsMixin:
    """Collects what the clients recorded and matches it against exported blocks."""

    clients: list[EmulatorClient]

    if TYPE_CHECKING:
        pass

    def collect_round_events(self) -> list[dict[str, object]]:
        """Producer-owned round records from every client that started a coinjoin."""
        events: list[dict[str, object]] = []
        for client in self.clients:
            events.extend(dict(event) for event in getattr(client, "round_events", []))
        return events

    def _script_addresses(self, output: dict[str, object]) -> list[object]:
        script_pub_key = cast(dict[str, object], output.get("scriptPubKey") or {})
        addresses: list[object] = []
        if script_pub_key.get("address"):
            addresses.append(script_pub_key["address"])
        addresses.extend(cast(list[object], script_pub_key.get("addresses") or []))
        return addresses

    def _reconcile_exported_match(self, event: dict[str, object], txid: object, block_height: object) -> None:
        existing_txid = event.get("txid")
        if existing_txid and existing_txid != txid:
            additional = cast(list[dict[str, object]], event.setdefault("additional_destination_matches", []))
            candidate: dict[str, object] = {"txid": txid, "block_height": block_height}
            if candidate not in additional:
                additional.append(candidate)
            return
        event["status"] = "confirmed"
        event["txid"] = txid
        event["block_height"] = block_height
        event["confirmed_chain_height"] = block_height
        event["match_source"] = "destination_output"

    def match_joinmarket_rounds_to_blocks(self, data_path: str) -> list[dict[str, object]]:
        """Match each recorded round to the mined transaction paying its destination."""
        labels_by_destination = {
            event["destination_address"]: event
            for event in self.collect_round_events()
            if event.get("destination_address")
        }
        if not labels_by_destination:
            return []

        node_path = os.path.join(data_path, "btc-node")
        if not os.path.isdir(node_path):
            return list(labels_by_destination.values())

        for filename in sorted(os.listdir(node_path)):
            if not filename.startswith("block_") or not filename.endswith(".json"):
                continue
            with open(os.path.join(node_path, filename), encoding="utf-8") as f:
                block = json.load(f)
            block_height = block.get("height")
            for tx in block.get("tx", []):
                txid = tx.get("txid")
                if not txid:
                    continue
                for output in tx.get("vout", []):
                    for address in self._script_addresses(output):
                        event = labels_by_destination.get(address)
                        if event is not None:
                            self._reconcile_exported_match(event, txid, block_height)

        return sorted(
            labels_by_destination.values(),
            key=lambda event: (event.get("round_id", 0), event.get("taker", "")),
        )

    def store_round_events(self, data_path: str) -> dict[str, object]:
        labels = self.match_joinmarket_rounds_to_blocks(data_path)
        with open(os.path.join(data_path, "joinmarket_round_events.json"), "w", encoding="utf-8") as f:
            json.dump(labels, f, indent=2)
        print(f"- stored {len(labels)} JoinMarket round labels")
        return {
            "engine": "joinmarket",
            "complete": True,
            "reason": None,
            "positive_rule": "exported transaction matches a reconciled JoinMarket round event",
            "positive_count": len({
                label["txid"] for label in labels
                if label.get("status") == "confirmed" and label.get("txid")
            }),
            "sources": ["joinmarket_round_events.json"],
        }
