import requests

WALLET_NAME = "wallet"
PASSWORD = "password"
WALLET_TYPE = "sw"
BTC = 100_000_000
JsonDict = dict[str, object]
STOP_SERVICE_NOT_RUNNING_MESSAGE = "Service cannot be stopped as it is not running"


def is_stop_service_not_running_error(error: Exception) -> bool:
    return STOP_SERVICE_NOT_RUNNING_MESSAGE in str(error)


class JoinmarketConflictException(Exception):
    def __init__(self, message: str, response: requests.Response) -> None:
        super().__init__(message)
        self.response = response
