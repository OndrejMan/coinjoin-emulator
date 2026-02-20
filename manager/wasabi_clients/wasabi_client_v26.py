from time import time, sleep
from traceback import print_exception

from .wasabi_client_base import WALLET_NAME, WasabiClientBase


class WasabiClientV26(WasabiClientBase):

    def __init__(
        self,
        host="localhost",
        port=37128,
        name="wasabi-client",
        proxy="",
        version="2.6.0",
        delay=(0, 0),
        stop=(0, 0),
    ):
        super().__init__(host, port, name, proxy, version, delay, stop)

    def wait_wallet(self, timeout=None):
        start = time()
        counter = 0
        while timeout is None or time() - start < timeout:
            try:
                self._create_wallet()
            except Exception as e:
                pass

            try:
                self.get_balance(timeout=5)
                return True
            except Exception as e:
                pass

            sleep(1)
        return False
