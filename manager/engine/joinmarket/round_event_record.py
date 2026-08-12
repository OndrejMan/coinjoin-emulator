"""Working representation of serialized JoinMarket round-event data."""

from typing import TypedDict

RoundEvent = dict[str, object]


class DestinationMatch(TypedDict):
    """One validated destination-output match in an exported round event."""

    txid: str
    block_height: int

EVENT_STATUS_CONFIRMED = "confirmed"
EVENT_STATUS_AMBIGUOUS = "ambiguous"
MATCH_SOURCE_DESTINATION_OUTPUT = "destination_output"


class RoundEventRecord:
    """Working representation of one serialized round-event dictionary."""

    def __init__(self, data: RoundEvent) -> None:
        self._data = data

    @classmethod
    def from_data(cls, data: RoundEvent) -> "RoundEventRecord":
        """Wrap one producer-owned event at a serialization boundary."""
        return cls(data)

    def copy_with_export_round_id(self, export_round_id: int) -> RoundEvent:
        """Copy this record for export and assign its stable global identifier."""
        return {**self._data, "export_round_id": export_round_id}

    def to_data(self) -> RoundEvent:
        """Return the JSON-serializable representation at the public boundary."""
        return dict(self._data)

    @property
    def destination_address(self) -> str | None:
        """Return the destination address when the producer supplied one."""
        address = self._data.get("destination_address")
        return address if isinstance(address, str) and address else None

    @property
    def status(self) -> str | None:
        """Return the current round status."""
        status = self._data.get("status")
        return status if isinstance(status, str) else None

    @property
    def export_round_id(self) -> int:
        """Return the mandatory global identifier assigned during event export."""
        value = self._data["export_round_id"]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("export_round_id must be an integer")
        return value

    @property
    def round_id(self) -> int | None:
        """Return the producer's original per-client round identifier when valid."""
        value = self._data.get("round_id")
        return value if isinstance(value, int) else None

    @property
    def taker(self) -> str:
        """Return the producer's taker name for deterministic ordering."""
        taker = self._data.get("taker")
        return taker if isinstance(taker, str) else ""

    def add_destination_match(self, txid: str, block_height: int) -> None:
        """Record one exported transaction and update the reconciliation status."""
        matches = self._destination_matches()
        candidate: DestinationMatch = {"txid": txid, "block_height": block_height}
        if candidate not in matches:
            matches.append(candidate)
        self._data["status"] = EVENT_STATUS_CONFIRMED if len(matches) == 1 else EVENT_STATUS_AMBIGUOUS
        self._data["match_source"] = MATCH_SOURCE_DESTINATION_OUTPUT

    def confirmed_destination_txid(self) -> str | None:
        """Return the sole reconciled transaction ID, if this record is unambiguous."""
        matches = self._destination_matches()
        if self.status != EVENT_STATUS_CONFIRMED or len(matches) != 1:
            return None
        return matches[0]["txid"]

    def _destination_matches(self) -> list[DestinationMatch]:
        """Return and persist only matches satisfying the exported event contract."""
        raw_matches = self._data.get("destination_matches")
        if not isinstance(raw_matches, list):
            raw_matches = []
        matches = [
            DestinationMatch(txid=txid, block_height=block_height)
            for raw_match in raw_matches
            if isinstance(raw_match, dict)
            if isinstance(txid := raw_match.get("txid"), str) and txid
            if isinstance(block_height := raw_match.get("block_height"), int) and not isinstance(block_height, bool)
        ]
        self._data["destination_matches"] = matches
        return matches
