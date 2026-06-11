import requests
import json
from time import monotonic, sleep

WALLET = "wallet"


class BtcNode:
    def __init__(self, host="localhost", port=18443, internal_ip="", proxy=""):
        self.host = host
        self.port = port
        self.internal_ip = internal_ip
        self.proxy = proxy

    def _rpc(self, request, wallet=None):
        request["jsonrpc"] = "1.0"
        request["id"] = "1"
        response = requests.post(
            f"http://{self.host}:{self.port}" + ("/wallet/" + WALLET if wallet else ""),
            data=json.dumps(request),
            auth=("user", "password"),
            proxies=dict(http=self.proxy),
            timeout=5,
        )
        response.raise_for_status()
        if response.json()["error"] is not None:
            raise Exception(response.json()["error"])
        return response.json()["result"]

    def get_block_count(self):
        request = {
            "method": "getblockcount",
            "params": [],
        }
        return self._rpc(request)

    def get_block_hash(self, height):
        request = {
            "method": "getblockhash",
            "params": [height],
        }
        return self._rpc(request)

    def get_block_info(self, block_hash):
        request = {
            "method": "getblock",
            "params": [block_hash, 2],
        }
        return self._rpc(request)

    def mine_block(self, count=1):
        initial_block_count = self.get_block_count()

        request = {
            "method": "getnewaddress",
            "params": [],
        }
        address = self._rpc(request, WALLET)

        request = {
            "method": "generatetoaddress",
            "params": [count, address],
        }
        self._rpc(request)

        return self.get_block_count() - initial_block_count == count

    def fund_address(self, address, amount):
        request = {
            "method": "sendtoaddress",
            "params": [address, amount],
        }
        self._rpc(request, WALLET)

    def wait_ready(self, timeout=300):
        deadline = monotonic() + timeout
        last_error = None
        last_block_count = None

        while monotonic() < deadline:
            try:
                block_count = self.get_block_count()
                last_block_count = block_count
                if block_count > 200:
                    break
            except Exception as exc:
                last_error = exc
            sleep(0.1)
        else:
            detail = f"last block count: {last_block_count}"
            if last_error is not None:
                detail = f"last error: {last_error}"
            raise TimeoutError(
                f"btc-node RPC at {self.host}:{self.port} was not ready after {timeout}s ({detail})"
            )

        # wait for the fee-building transactions
        sleep(20)

    def create_wallet(self, wallet):
        request = {
            "method": "createwallet",
            "params": {"wallet_name": "jm_wallet", "descriptors": False},
        }

        request["jsonrpc"] = "2.0"
        request["id"] = "1"
        try:
            response = requests.post(
                f"http://{self.host}:{self.port}",
                data=json.dumps(request),
                auth=("user", "password"),
                proxies=dict(http=self.proxy),
                timeout=5,
            )
        except requests.exceptions.Timeout:
            print("timeout")
        if response.json()["error"] is not None:
            print(response.json())
            raise Exception(response.json()["error"])
        print(response.json())
