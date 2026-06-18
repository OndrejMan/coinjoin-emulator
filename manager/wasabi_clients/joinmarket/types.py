import requests

WALLET_NAME = "wallet"
PASSWORD = "password"
WALLET_TYPE = "sw"
BTC = 100_000_000
JsonDict = dict[str, object]


class JoinmarketConflictException(Exception):
    def __init__(self, message: str, response: requests.Response) -> None:
        super().__init__(message)
        self.response = response
