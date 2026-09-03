"""Shared types and constants for the JoinMarket client."""

from typing import TypedDict

JsonDict = dict[str, object]

WALLET_NAME = "wallet"
DEFAULT_WAIT_WALLET_TIMEOUT = 60
PASSWORD = "password"
WALLET_TYPE = "sw"
BTC = 100_000_000


class BondRecord(TypedDict):
    """Bookkeeping for one fidelity bond this client created."""

    amount: int
    locktime: str
    creation_block: int
    funded: bool


class JoinmarketConflictException(Exception):
    def __init__(self, message: str, response: object) -> None:
        super().__init__(message)
        self.response = response
