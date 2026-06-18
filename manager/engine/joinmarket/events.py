import json
import os
from typing import cast

from ...btc_node import BtcNode


class JoinMarketRoundEventsMixin:
    node: BtcNode | None
    joinmarket_round_events: list[dict[str, object]]
    current_block: int
    current_round = 0

    def store_engine_logs(self, data_path: str) -> None:
        labels = self.match_joinmarket_rounds_to_blocks(data_path)
        with open(
            os.path.join(data_path, "joinmarket_round_events.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(labels, f, indent=2)
            print("- stored JoinMarket round labels")

    def match_joinmarket_rounds_to_blocks(self, data_path: str) -> list[dict[str, object]]:
        labels_by_destination = {
            event["destination_address"]: dict(event)
            for event in self.joinmarket_round_events
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
                block = cast(dict[str, object], json.load(f))
            block_height = block.get("height")
            for tx in cast(list[dict[str, object]], block.get("tx", [])):
                txid = tx.get("txid")
                for event in labels_by_destination.values():
                    matching_outputs = self._matching_coinjoin_outputs(event, tx)
                    if not matching_outputs:
                        continue
                    for output in matching_outputs:
                        if event["destination_address"] in self._script_addresses(output) and txid:
                            event["txid"] = txid
                            event["block_height"] = block_height
                            event["match_source"] = "destination_output"

        return sorted(
            labels_by_destination.values(),
            key=lambda event: (event.get("round_id", 0), event.get("taker", "")),
        )

    def _script_addresses(self, output: dict[str, object]) -> list[object]:
        script_pub_key = cast(dict[str, object], output.get("scriptPubKey") or {})
        addresses: list[object] = []
        if script_pub_key.get("address"):
            addresses.append(script_pub_key["address"])
        addresses.extend(cast(list[object], script_pub_key.get("addresses") or []))
        return addresses

    def _matching_coinjoin_outputs(
        self, event: dict[str, object], tx: dict[str, object]
    ) -> list[dict[str, object]]:
        outputs = cast(list[dict[str, object]], tx.get("vout", []))
        if not event.get("amount_sats") or not event.get("counterparties"):
            return outputs

        amount_btc = float(str(event.get("amount_sats", 0))) / 100_000_000
        expected_outputs_count = int(str(event.get("counterparties", 0))) + 1
        matching_outputs = [
            output for output in outputs
            if abs(float(str(output.get("value", 0))) - amount_btc) < 1e-8
        ]
        if len(matching_outputs) < expected_outputs_count:
            return []
        return matching_outputs

    def _find_round_event_tx(self, event: dict[str, object]) -> dict[str, object] | None:
        if event.get("txid"):
            return {
                "txid": event.get("txid"),
                "block_height": event.get("block_height"),
            }
        if self.node is None or not event.get("destination_address"):
            return None

        start_height = max(0, int(str(event.get("start_chain_height") or 0)))
        tip_height = self.node.get_block_count()

        for height in range(start_height, tip_height + 1):
            block_hash = self.node.get_block_hash(height)
            block = self.node.get_block_info(block_hash)
            for tx in cast(list[dict[str, object]], block.get("tx", [])):
                txid = tx.get("txid")
                matching_outputs = self._matching_coinjoin_outputs(event, tx)
                for output in matching_outputs:
                    if event["destination_address"] in self._script_addresses(output):
                        return {
                            "txid": txid,
                            "block_height": block.get("height", height),
                        }
        return None

    def confirm_started_rounds(self) -> int:
        confirmed = 0
        for event in self.joinmarket_round_events:
            if event.get("status") != "started":
                continue

            match = self._find_round_event_tx(event)
            if not match:
                continue

            event["status"] = "confirmed"
            event["txid"] = match.get("txid")
            event["block_height"] = match.get("block_height")
            event["confirmed_block"] = self.current_block
            self.current_round += 1
            confirmed += 1
            print(f"Confirmed coinjoin {event.get('taker')} as {event.get('txid')}")
        return confirmed
