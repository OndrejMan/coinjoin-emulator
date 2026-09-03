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
        response = requests.post(
            f"http://{self.host}:{self.port}" + (f"/wallet/{wallet}" if wallet else ""),
            data=json.dumps(request),
            auth=("user", "password"),
            proxies=dict(http=self.proxy),
            timeout=5,
        )
        body = response.json()
        if body["error"] is not None:
            raise RpcError(body["error"])
        return body["result"]

    def get_block_count(self):
        request = {
            "method": "getblockcount",
            "params": [],
        }
        result = self._rpc(request)
        if not isinstance(result, int):
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

    def create_wallet(self, wallet, disable_private_keys=False, allow_descriptor_fallback=True):
        body = self._create_wallet(wallet, descriptors=False, disable_private_keys=disable_private_keys)
        error = body.get("error")
        if error is not None and allow_descriptor_fallback and self._is_bdb_wallet_creation_error(error):
            # Core 26+ rejects legacy BDB wallet creation by default:
            # https://bitcoincore.org/en/releases/26.0/#wallet
            # Core 29.1 defaults WITH_BDB to OFF, and the project's Alpine
            # image does not enable it:
            # https://github.com/bitcoin/bitcoin/blob/v29.1/CMakeLists.txt#L119-L124
            # https://github.com/willcl-ark/bitcoin-core-docker/blob/f340c3f16fe039a3305b70f5f850befe3b5163e3/deprecated/29.1/alpine/Dockerfile
            # The resulting createwallet error is implemented here:
            # https://github.com/bitcoin/bitcoin/blob/v29.1/src/wallet/rpc/wallet.cpp#L405-L427
            # Therefore retry with a descriptor wallet.
            body = self._create_wallet(wallet, descriptors=True, disable_private_keys=disable_private_keys)
            error = body.get("error")
        if error is not None and self._is_wallet_database_exists_error(error):
            # A wallet left behind by an earlier run only needs loading.
            try:
                self._rpc({"method": "loadwallet", "params": [wallet]})
            except RpcError as load_error:
                if "already loaded" not in str(load_error):
                    raise
            self._rpc({"method": "getwalletinfo", "params": []}, wallet)
            return
        if error is not None:
            raise RpcError(str(error))

    def _create_wallet(self, wallet: str, descriptors: bool, disable_private_keys: bool) -> dict:
        request = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "createwallet",
            "params": {
                "wallet_name": wallet,
                "descriptors": descriptors,
                "disable_private_keys": disable_private_keys,
            },
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
        if not isinstance(body, dict) or ("error" not in body and "result" not in body):
            raise RpcError(f"Unexpected btc-node response creating wallet {wallet}: {body!r}")
        return body

    @staticmethod
    def _is_bdb_wallet_creation_error(error: object) -> bool:
        message = str(error.get("message", "")) if isinstance(error, dict) else ""
        return isinstance(error, dict) and error.get("code") == -4 and (
            "BDB wallet creation is deprecated" in message or "Compiled without bdb support" in message
        )

    @staticmethod
    def _is_wallet_database_exists_error(error: object) -> bool:
        return (
            isinstance(error, dict)
            and error.get("code") == -4
            and "Database already exists" in str(error.get("message", ""))
        )
