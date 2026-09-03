import json
from time import sleep

import requests

from .exceptions import RpcError

WALLET = "wallet"


class BtcNode:
    def __init__(self, host="localhost", port=18443, internal_ip="", proxy=""):
        self.host = host
        self.port = port
        self.internal_ip = internal_ip
        self.proxy = proxy

        print(f"Started btc-node with ip: {self.host} and ports: {self.port}")

    def _rpc(self, request, wallet=None):
        request["jsonrpc"] = "1.0"
        request["id"] = "1"
        try:
            response = requests.post(
                f"http://{self.host}:{self.port}" + (f"/wallet/{wallet}" if wallet else ""),
                data=json.dumps(request),
                auth=("user", "password"),
                proxies=dict(http=self.proxy),
                timeout=5,
            )
        except requests.exceptions.Timeout as e:
            print("Request timeout")
            print(e)
            return "timeout"
        if response.json()["error"] is not None:
            raise Exception(response.json()["error"])
        return response.json()["result"]

    def get_block_count(self):
        request = {
            "method": "getblockcount",
            "params": [],
        }
        result = self._rpc(request)
        if not isinstance(result, int):
            # _rpc answers "timeout" instead of a result when the node does not
            # respond; callers should see that as a failure, not as a height.
            raise RpcError(f"btc-node returned no block count: {result!r}")
        return result

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

    def wait_ready(self):
        while True:
            try:
                if self.get_block_count() > 200:
                    break
            except Exception as e:
                print(f"Btc node not ready: {e}")
                pass
            sleep(10)

        # wait for the fee-building transactions
        sleep(20)

    def create_wallet(self, wallet):
        request = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "createwallet",
            "params": {"wallet_name": wallet, "descriptors": False},
        }

        try:
            response = requests.post(
                f"http://{self.host}:{self.port}",
                data=json.dumps(request),
                auth=("user", "password"),
                proxies=dict(http=self.proxy),
                timeout=5,
            )
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"btc-node RPC timed out creating wallet {wallet}") from e
        body = response.json()
        if body["error"] is not None:
            print(body)
            raise RpcError(str(body["error"]))
        print(body)
