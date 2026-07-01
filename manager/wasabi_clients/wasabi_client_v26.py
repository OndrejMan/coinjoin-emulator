from time import sleep, time

import requests

from ..exceptions import RpcError
from .wasabi_client_base import WasabiClientBase


class WasabiClientV26(WasabiClientBase):

    def __init__(
        self,
        host: str = "localhost",
        port: int = 37128,
        name: str = "wasabi-client",
        proxy: str = "",
        version: str = "2.6.0",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
    ) -> None:
        super().__init__(host, port, name, proxy, version, delay, stop)

    def wait_wallet(self, timeout: int | None = None) -> bool:
        start = time()
        while timeout is None or time() - start < timeout:
            try:
                self._create_wallet()
            except (requests.exceptions.RequestException, RpcError, KeyError, TypeError, ValueError):
                pass

            try:
                self.get_balance(timeout=5)
                return True
            except (requests.exceptions.RequestException, RpcError, KeyError, TypeError, ValueError):
                pass

            sleep(1)
        return False
