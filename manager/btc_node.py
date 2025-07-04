import requests
import json
from time import sleep

WALLET = "wallet"


class BtcNode:
    def __init__(self, host="localhost", port=18443, internal_ip="", proxy=""):
        self.host = host
        self.port = port
        self.internal_ip = internal_ip
        self.proxy = proxy

        print(f"Started btc-node with ip: {self.host} and ports: {self.port}")

    def _rpc(self, request, wallet=None):
        request["jsonrpc"] = "2.0"
        request["id"] = "1"
        try:
            print(f"Request: {json.dumps(request)}")
            print(f"http://{self.host}:{self.port}")
            response = requests.post(
                f"http://{self.host}:{self.port}"
                + ("/wallet/" + WALLET if wallet else ""),
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

    def wait_ready(self):
        while True:
            try:
                block_count = self.get_block_count()
                print(f"Block count: {block_count}")
                if block_count == 'timeout':
                    print("Btc node not ready, timeout")
                    continue
                if block_count > 100:
                    break
            except Exception as e:
                print(f"Btc node not ready: {e}")
                pass
            sleep(10)

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