from __future__ import annotations

# pylint: disable=unused-argument
from typing import Protocol

class JsonRpc(Protocol):
    url: str
    def setURL(self, url: str) -> None: ...

class RegtestBitcoinCoreInterface:
    jsonRpc: JsonRpc
    def _rpc(self, method: str, params: list[object]) -> object: ...
