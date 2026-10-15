"""Typed view of the scriptPubKey portion of a transaction output."""

from typing import Self

ScriptPubKey = dict[str, object]


class ScriptPubKeyRecord:
    """View of the address fields exported for one scriptPubKey."""

    def __init__(self, data: ScriptPubKey) -> None:
        self._data = data

    @classmethod
    def from_data(cls, data: object) -> Self:
        """Create a safe view of one optionally present scriptPubKey object."""
        return cls(data if isinstance(data, dict) else {})

    @property
    def address(self) -> str | None:
        """Return the address exported by Bitcoin Core, when present."""
        address = self._data.get("address")
        return address if isinstance(address, str) and address else None
