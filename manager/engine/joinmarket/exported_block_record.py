"""Typed view of one Bitcoin block exported by the emulator."""

from collections.abc import Iterable
from typing import Self

from manager.engine.joinmarket.exported_transaction_record import ExportedTransactionRecord

ExportedBlock = dict[str, object]


class ExportedBlockRecord:
    """View of one Bitcoin block exported by the emulator."""

    def __init__(self, data: ExportedBlock) -> None:
        self._data = data

    @classmethod
    def from_data(cls, data: ExportedBlock) -> Self:
        """Create a view of one exported block."""
        return cls(data)

    @property
    def height(self) -> int | None:
        """Return the exported block height when it is a valid integer."""
        value = self._data.get("height")
        return value if isinstance(value, int) else None

    @property
    def transactions(self) -> Iterable[ExportedTransactionRecord]:
        """Iterate over the transactions in this block."""
        transactions = self._data.get("tx")
        if not isinstance(transactions, list):
            return ()
        return (ExportedTransactionRecord.from_data(transaction) for transaction in transactions)
