"""Typed view of one transaction in exported Bitcoin block JSON."""

from collections.abc import Iterable
from typing import Self

from manager.engine.joinmarket.transaction_output_record import TransactionOutputRecord

ExportedTransaction = dict[str, object]


class ExportedTransactionRecord:
    """View of one transaction in the exported block JSON."""

    def __init__(self, data: ExportedTransaction) -> None:
        self._data = data

    @classmethod
    def from_data(cls, data: object) -> Self:
        """Create a safe view of one exported transaction."""
        return cls(data if isinstance(data, dict) else {})

    @property
    def txid(self) -> str | None:
        """Return the transaction identifier when present and valid."""
        txid = self._data.get("txid")
        return txid if isinstance(txid, str) and txid else None

    @property
    def outputs(self) -> Iterable[TransactionOutputRecord]:
        """Iterate over the transaction outputs."""
        outputs = self._data.get("vout")
        if not isinstance(outputs, list):
            return ()
        return (TransactionOutputRecord.from_data(output) for output in outputs)
