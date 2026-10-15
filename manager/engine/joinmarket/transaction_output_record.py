"""Typed view of one exported Bitcoin transaction output."""

from typing import Self

from manager.engine.joinmarket.script_pub_key_record import ScriptPubKeyRecord

TransactionOutput = dict[str, object]


class TransactionOutputRecord:
    """View of one exported transaction output."""

    def __init__(self, data: TransactionOutput) -> None:
        self._data = data

    @classmethod
    def from_data(cls, data: object) -> Self:
        """Create a safe view of one exported transaction output."""
        return cls(data if isinstance(data, dict) else {})

    @property
    def script_pub_key(self) -> ScriptPubKeyRecord:
        """Return the output's scriptPubKey view."""
        return ScriptPubKeyRecord.from_data(self._data.get("scriptPubKey"))

    @property
    def address(self) -> str | None:
        """Return the address carried by this output, when present."""
        return self.script_pub_key.address
