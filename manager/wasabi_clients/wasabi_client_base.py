import json
import random
import requests
from time import sleep, time
from typing import cast

from ..exceptions import RpcError

WALLET_NAME = "wallet"


class WasabiClientBase:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 37128,
        name: str = "wasabi-client",
        proxy: str = "",
        version: str = "2.0.4",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
    ) -> None:
        self.host = host
        self.port = port
        self.name = name
        self.proxy = proxy
        self.version = version
        self.delay = delay
        self.stop = stop

    def _rpc(
        self,
        request: dict[str, object],
        wallet: bool | str = True,
        timeout: int | None = 5,
        repeat: int = 1,
        wallet_name: str | None = None,
    ) -> object:
        request["jsonrpc"] = "2.0"
        request["id"] = "1"

        if self.version < "2.0.4":
            wallet = False

        for _ in range(repeat):
            try:
                response = requests.post(
                    f"http://{self.host}:{self.port}/{(wallet_name or WALLET_NAME) if wallet else ''}",
                    data=json.dumps(request),
                    proxies=dict(http=self.proxy),
                    timeout=timeout,
                )
            except requests.exceptions.Timeout:
                continue
            if "error" in response.json():
                raise RpcError(str(response.json()["error"]))
            if "result" in response.json():
                return response.json()["result"]
            return None
        return "timeout"

    def get_status(self) -> object:
        request: dict[str, object] = {
            "method": "getstatus",
        }
        return self._rpc(request, wallet=False)

    def _create_wallet(self, wallet_name: str | None = None) -> object:
        request: dict[str, object] = {
            "method": "createwallet",
            "params": [wallet_name or WALLET_NAME, ""],
        }
        return self._rpc(request)

    def get_new_address(self) -> str:
        request: dict[str, object] = {
            "method": "getnewaddress",
            "params": ["label"],
        }
        res = cast(dict[str, object], self._rpc(request))["address"]
        if not isinstance(res, str):
            raise TypeError(f"Unexpected address response: {res}")
        return res

    def get_balance(self, timeout: int | None = None, wallet_name: str | None = None) -> int:
        request: dict[str, object] = {
            "method": "getwalletinfo",
        }
        balance = cast(dict[str, object], self._rpc(request, timeout=timeout, wallet_name=wallet_name))["balance"]
        if not isinstance(balance, int):
            raise TypeError(f"Unexpected balance response: {balance}")
        return balance

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

            sleep(0.1)
        return False

    def _list_unspent_coins(self) -> list[dict[str, object]]:
        request: dict[str, object] = {
            "method": "listunspentcoins",
        }
        return cast(list[dict[str, object]], self._rpc(request))

    def send(self, invoices: list[tuple[str, int]]) -> object:
        unspent_coins = self._list_unspent_coins()
        random.shuffle(unspent_coins)

        cost = sum(map(lambda x: x[1], invoices))
        coins: list[dict[str, object]] = []
        for coin in unspent_coins:
            coins.append({"transactionid": coin["txid"], "index": coin["index"]})
            cost -= int(str(coin["amount"]))
            if cost < 0:
                break
        else:
            raise RpcError("Not enough BTC")

        payments = list(map(lambda x: {"sendto": x[0], "amount": x[1]}, invoices))

        request: dict[str, object] = {
            "method": "send",
            "params": {
                "payments": payments,
                "coins": coins,
                "feeTarget": 2,
                "password": "",
            },
        }
        return self._rpc(request, timeout=None)

    def start_coinjoin(self) -> object:
        request: dict[str, object] = {
            "method": "startcoinjoin",
            "params": ["", "True", "True"],
        }
        return self._rpc(request, timeout=None)

    def stop_coinjoin(self) -> object:
        request: dict[str, object] = {
            "method": "stopcoinjoin",
        }
        return self._rpc(request, "wallet")

    def list_coins(self) -> object:
        request: dict[str, object] = {
            "method": "listcoins",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def list_unspent_coins(self) -> object:
        request: dict[str, object] = {
            "method": "listunspentcoins",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def list_keys(self) -> object:
        request: dict[str, object] = {
            "method": "listkeys",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def wait_ready(self) -> None:
        while True:
            try:
                self.get_status()
                break
            except (requests.exceptions.RequestException, RpcError, ValueError):
                pass
            sleep(0.1)
