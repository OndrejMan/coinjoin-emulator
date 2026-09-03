import json

import requests

from .bitcoin_readiness import wait_for_node_ready
from .exceptions import RpcError

WALLET = "wallet"
FUNDING_WALLET_TX_FEE = 0.0001


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

    def get_blockchain_info(self):
        return self._rpc({"method": "getblockchaininfo", "params": []})

    def estimate_smart_fee(self):
        return self._rpc({"method": "estimatesmartfee", "params": [6]})

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

    def wait_ready(self, timeout=600):
        """Wait until this node is ready for the emulator engines."""
        wait_for_node_ready(self, timeout)

    def ensure_funding_wallet_ready(self):
        """Load the shared funding wallet and set the fee the distributor pays."""
        if WALLET not in self._rpc({"method": "listwallets", "params": []}):
            try:
                self._rpc({"method": "loadwallet", "params": [WALLET]})
            except RpcError as error:
                if "already loaded" in str(error):
                    pass
                elif self._is_wallet_missing_error(error):
                    self.create_wallet(WALLET)
                else:
                    raise
        self._rpc({"method": "getwalletinfo", "params": []}, WALLET)
        self._rpc({"method": "settxfee", "params": [FUNDING_WALLET_TX_FEE]}, WALLET)

    @staticmethod
    def _is_wallet_missing_error(error):
        message = str(error)
        return any(
            marker in message
            for marker in (
                "Path does not exist",
                "not found",
                "No such file or directory",
                "Wallet file verification failed",
            )
        )

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
