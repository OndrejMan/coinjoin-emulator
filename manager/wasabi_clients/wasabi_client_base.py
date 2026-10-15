import json
import random
from collections.abc import Callable
from time import monotonic, sleep, time
from typing import TypedDict

import requests

from manager.exceptions import RpcError

WALLET_NAME = "wallet"

RETRY_BACKOFF_SECONDS = 1
JSON_RPC_INTERNAL_ERROR = -32603

TRANSIENT_INTERNAL_ERRORS = (
    "Destination array was not long enough",
    "Collection was modified",
)


class WasabiCoin(TypedDict):
    """The ``listunspentcoins`` fields that mixed-coin selection reads."""
    txid: str
    index: int
    amount: int
    anonymityScore: float
    confirmed: bool


def _is_transient(error) -> bool:
    return (
        isinstance(error, dict)
        and error.get("code") == JSON_RPC_INTERNAL_ERROR
        and any(fragment in str(error.get("message", "")) for fragment in TRANSIENT_INTERNAL_ERRORS)
    )


class WasabiClientBase:
    def __init__(
        self,
        host="localhost",
        port=37128,
        name="wasabi-client",
        proxy="",
        version="2.0.4",
        delay=(0, 0),
        stop=(0, 0),
        skip_rounds=(),
    ):
        self.host = host
        self.port = port
        self.name = name
        self.proxy = proxy
        self.version = version
        self.delay = delay
        self.stop = stop
        self.skip_rounds = frozenset(skip_rounds)

    def _rpc(self, request, wallet=True, timeout=5, repeat=1, wallet_name=None):
        request["jsonrpc"] = "2.0"
        request["id"] = "1"

        if self.version < "2.0.4":
            wallet = False

        last_error = None
        for attempt in range(repeat):
            try:
                response = requests.post(
                    f"http://{self.host}:{self.port}/{(wallet_name or WALLET_NAME) if wallet else ''}",
                    data=json.dumps(request),
                    proxies=dict(http=self.proxy),
                    timeout=timeout,
                )
            except requests.exceptions.Timeout as error:
                last_error = error
                if attempt + 1 < repeat:
                    sleep(RETRY_BACKOFF_SECONDS)
                continue
            if "error" in response.json():
                error = response.json()["error"]
                if _is_transient(error) and attempt + 1 < repeat:
                    sleep(RETRY_BACKOFF_SECONDS)
                    continue
                raise RpcError(error)
            if "result" in response.json():
                return response.json()["result"]
            return None
        if last_error is not None:
            raise last_error
        raise RpcError(f"no answer from {self.host}:{self.port} after {repeat} attempts")

    def get_status(self):
        request = {
            "method": "getstatus",
        }
        return self._rpc(request, wallet=False)

    def _create_wallet(self, wallet_name: str | None = None):
        request = {
            "method": "createwallet",
            "params": [wallet_name or WALLET_NAME, ""],
        }
        return self._rpc(request)

    def get_new_address(self):
        request = {
            "method": "getnewaddress",
            "params": ["label"],
        }
        res = self._rpc(request, repeat=3)["address"]
        return res

    def get_wallet_info(self, timeout=None, wallet_name=None):
        request = {
            "method": "getwalletinfo",
        }
        return self._rpc(request, timeout=timeout, wallet_name=wallet_name)

    def get_balance(self, timeout=None, wallet_name=None):
        return self.get_wallet_info(timeout=timeout, wallet_name=wallet_name)["balance"]

    def wallet_started(self, timeout=None) -> bool:
        info = self.get_wallet_info(timeout=timeout)
        return "balance" in info and info.get("state", "Started") == "Started"

    def wait_wallet(self, timeout=None):
        start = time()
        while timeout is None or time() - start < timeout:
            try:
                self._create_wallet()
            except Exception:
                pass

            try:
                if self.wallet_started(timeout=5):
                    return True
            except Exception:
                pass

            sleep(0.1)
        return False

    def _list_unspent_coins(self):
        request = {
            "method": "listunspentcoins",
        }
        return self._rpc(request)

    def send(self, invoices):
        unspent_coins = self._list_unspent_coins()
        random.shuffle(unspent_coins)

        cost = sum(map(lambda x: x[1], invoices))
        coins = []
        for coin in unspent_coins:
            coins.append({"transactionid": coin["txid"], "index": coin["index"]})
            cost -= coin["amount"]
            if cost < 0:
                break
        else:
            raise Exception("Not enough BTC")

        payments = list(map(lambda x: {"sendto": x[0], "amount": x[1]}, invoices))

        request = {
            "method": "send",
            "params": {
                "payments": payments,
                "coins": coins,
                "feeTarget": 2,
                "password": "",
            },
        }
        return self._rpc(request, timeout=None)

    def send_mixed_coins(
        self,
        destination: str,
        value: int | None = None,
        min_anon_score: float | None = None,
        unspent: Callable[[str, int], bool] | None = None,
    ) -> dict[str, object]:
        """Spend mixed coins to ``destination`` in one transaction without change.

        Confirmed coins with an anonymity score of at least ``min_anon_score``
        (default: above 1, i.e. coins that went through a coinjoin) are taken from
        the most private down until they cover ``value``, or all of them when
        ``value`` is None. The whole selection is paid out with the fee subtracted,
        so no change output re-enters the wallet as fresh liquidity. ``unspent``
        drops coins the node already sees spent; see ``_select_mixed_coins``.
        """
        selected, total = self._select_mixed_coins(value, min_anon_score, unspent)
        request = {
            "method": "send",
            "params": {
                "payments": [{"sendto": destination, "amount": total, "label": "postmix", "subtractFee": True}],
                "coins": [{"transactionid": coin["txid"], "index": coin["index"]} for coin in selected],
                "feeTarget": 2,
                "password": "",
            },
        }
        result = self._rpc(request, timeout=None)
        return {
            "txid": result.get("txid") if isinstance(result, dict) else None,
            "amount_sats": total,
            "coins": [
                {
                    "txid": coin["txid"],
                    "index": coin["index"],
                    "amount": coin["amount"],
                    "anonymity_score": coin["anonymityScore"],
                }
                for coin in selected
            ],
        }

    def check_mixed_coins(
        self,
        value: int | None = None,
        min_anon_score: float | None = None,
        unspent: Callable[[str, int], bool] | None = None,
    ) -> None:
        """Raise like ``send_mixed_coins`` when the mixed coins cannot cover ``value`` yet."""
        self._select_mixed_coins(value, min_anon_score, unspent)

    def _select_mixed_coins(
        self,
        value: int | None = None,
        min_anon_score: float | None = None,
        unspent: Callable[[str, int], bool] | None = None,
    ) -> tuple[list[WasabiCoin], int]:
        """Most private confirmed mixed coins covering ``value`` (all of them when None), and their sum.

        The wallet sees no mempool, so a coinjoin it just signed leaves its inputs
        listed as unspent until a block confirms it; spending them again is a
        low-fee replacement the node rejects. ``unspent`` asks the node instead.
        """
        def is_mixed(coin: WasabiCoin) -> bool:
            score = coin.get("anonymityScore") or 0
            return score > 1 if min_anon_score is None else score >= min_anon_score

        candidates = sorted(
            (
                coin
                for coin in self._list_unspent_coins()
                if coin.get("confirmed")
                and is_mixed(coin)
                and (unspent is None or unspent(coin["txid"], coin["index"]))
            ),
            key=lambda coin: coin["anonymityScore"],
            reverse=True,
        )
        selected = []
        total = 0
        for coin in candidates:
            if value is not None and total >= value:
                break
            selected.append(coin)
            total += coin["amount"]
        if not selected or (value is not None and total < value):
            raise RuntimeError(f"{self.name} has {total} sats of mixed coins, {value or 'any'} sats requested")
        return selected, total

    def start_coinjoin(self):
        request = {
            "method": "startcoinjoin",
            "params": ["", "True", "True"],
        }
        return self._rpc(request, timeout=None)

    def stop_coinjoin(self):
        request = {
            "method": "stopcoinjoin",
        }
        return self._rpc(request, "wallet")

    def list_coins(self):
        request = {
            "method": "listcoins",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def list_unspent_coins(self):
        request = {
            "method": "listunspentcoins",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def list_keys(self):
        request = {
            "method": "listkeys",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def get_history(self):
        request = {
            "method": "gethistory",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def wait_ready(self, timeout=120):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            try:
                self.get_status()
                return
            except Exception:
                pass
            sleep(0.1)
        raise TimeoutError(f"{self.__class__.__name__} at {self.host}:{self.port} was not ready after {timeout}s")
