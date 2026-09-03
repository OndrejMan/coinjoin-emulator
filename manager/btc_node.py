import json
from time import monotonic, sleep
from typing import cast

import requests

from .exceptions import RpcError

WALLET = "wallet"
FUNDING_WALLET_TX_FEE = 0.0001
QUIET_SAMPLE_COUNT = 6
QUIET_SAMPLE_INTERVAL_SECONDS = 0.5


class BtcNode:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 18443,
        internal_ip: str = "",
        proxy: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.internal_ip = internal_ip
        self.proxy = proxy

        print(f"Started btc-node with ip: {self.host} and ports: {self.port}")

    def _rpc(self, request: dict[str, object], wallet: str | None = None) -> object:
        request["jsonrpc"] = "1.0"
        request["id"] = "1"
        response = requests.post(
            f"http://{self.host}:{self.port}" + (f"/wallet/{wallet}" if wallet else ""),
            data=json.dumps(request),
            auth=("user", "password"),
            proxies={"http": self.proxy},
            timeout=5,
        )
        try:
            body = response.json()
        except ValueError as error:
            response.raise_for_status()
            raise RpcError(f"Unexpected Bitcoin Core RPC response: {response.text}") from error
        if not isinstance(body, dict) or "error" not in body or "result" not in body:
            raise RpcError(f"Unexpected Bitcoin Core RPC response: {body!r}")
        if body["error"] is not None:
            raise RpcError(str(body["error"]))
        response.raise_for_status()
        return body["result"]

    def get_block_count(self) -> int:
        request: dict[str, object] = {
            "method": "getblockcount",
            "params": [],
        }
        result = self._rpc(request)
        if not isinstance(result, int):
            # _rpc answers "timeout" instead of a result when the node does not
            # respond; callers should see that as a failure, not as a height.
            raise RpcError(f"btc-node returned no block count: {result!r}")
        return result

    def get_blockchain_info(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            self._rpc({"method": "getblockchaininfo", "params": []}),
        )

    def get_block_hash(self, height: int) -> str:
        request: dict[str, object] = {
            "method": "getblockhash",
            "params": [height],
        }
        return cast(str, self._rpc(request))

    def get_block_info(self, block_hash: str) -> dict[str, object]:
        request: dict[str, object] = {
            "method": "getblock",
            "params": [block_hash, 2],
        }
        return cast(dict[str, object], self._rpc(request))

    def mine_block(self, count: int = 1) -> bool:
        initial_block_count = self.get_block_count()

        request: dict[str, object] = {
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

    def fund_address(self, address: str, amount: int | float) -> None:
        request: dict[str, object] = {
            "method": "sendtoaddress",
            "params": [address, amount],
        }
        self._rpc(request, WALLET)

    def estimate_smart_fee(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            self._rpc({"method": "estimatesmartfee", "params": [6]}),
        )

    def wait_ready(self, timeout: int = 600) -> None:
        deadline = monotonic() + timeout
        last_state = "no successful RPC sample"
        while monotonic() < deadline:
            try:
                block_count = self.get_block_count()
                info = self.get_blockchain_info()
                progress = info.get("verificationprogress")
                synchronized = (
                    block_count > 200
                    and info.get("headers") == block_count
                    and info.get("initialblockdownload") is False
                    and isinstance(progress, (int, float))
                    and progress >= 1.0
                )
                last_state = (
                    f"blocks={block_count} headers={info.get('headers')} "
                    f"initialblockdownload={info.get('initialblockdownload')} progress={progress}"
                )
                if synchronized:
                    self.ensure_funding_wallet_ready()
                    break
            except (requests.exceptions.RequestException, RpcError) as error:
                last_state = f"RPC error: {error}"
            sleep(0.1)
        else:
            raise TimeoutError(
                f"btc-node RPC at {self.host}:{self.port} was not ready after {timeout}s ({last_state})"
            )

        self.wait_fee_building_complete(max(0.0, deadline - monotonic()))

    def wait_fee_building_complete(self, timeout: float = 300) -> None:
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            try:
                if self.estimate_smart_fee().get("feerate") is not None:
                    break
            except (requests.exceptions.RequestException, RpcError):
                pass
            sleep(1)
        else:
            raise TimeoutError(f"btc-node produced no smart fee estimate after {timeout:.0f}s")

        streak = 0
        quiet_height: int | None = None
        while monotonic() < deadline:
            try:
                info = self.get_blockchain_info()
                blocks = info.get("blocks")
                progress = info.get("verificationprogress")
                synchronized = (
                    isinstance(blocks, int)
                    and blocks == info.get("headers")
                    and info.get("initialblockdownload") is False
                    and isinstance(progress, (int, float))
                    and progress >= 1.0
                )
                if synchronized and blocks == quiet_height:
                    streak += 1
                elif synchronized:
                    quiet_height = cast(int, blocks)
                    streak = 1
                else:
                    quiet_height = None
                    streak = 0
                if streak >= QUIET_SAMPLE_COUNT:
                    return
            except (requests.exceptions.RequestException, RpcError):
                quiet_height = None
                streak = 0
            sleep(QUIET_SAMPLE_INTERVAL_SECONDS)
        raise TimeoutError(f"btc-node did not become quietly synchronized after {timeout:.0f}s")

    def ensure_funding_wallet_ready(self) -> None:
        loaded = cast(list[str], self._rpc({"method": "listwallets", "params": []}))
        if WALLET not in loaded:
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

    def create_wallet(
        self,
        wallet: str,
        disable_private_keys: bool = False,
        allow_descriptor_fallback: bool = True,
    ) -> None:
        body = self._create_wallet(wallet, descriptors=False, disable_private_keys=disable_private_keys)
        error = body.get("error")
        if error is not None and allow_descriptor_fallback and self._is_bdb_wallet_creation_error(error):
            body = self._create_wallet(wallet, descriptors=True, disable_private_keys=disable_private_keys)
            error = body.get("error")
        if error is not None and self._is_wallet_database_exists_error(error):
            try:
                self._rpc({"method": "loadwallet", "params": [wallet]})
            except RpcError as load_error:
                if "already loaded" not in str(load_error):
                    raise
            self._rpc({"method": "getwalletinfo", "params": []}, wallet)
            return
        if error is not None:
            raise RpcError(str(error))

    def _create_wallet(
        self, wallet: str, descriptors: bool, disable_private_keys: bool
    ) -> dict[str, object]:
        request: dict[str, object] = {
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
                proxies={"http": self.proxy},
                timeout=5,
            )
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"btc-node RPC timed out creating wallet {wallet}") from e
        try:
            body = response.json()
        except ValueError as error:
            response.raise_for_status()
            raise RpcError(f"Unexpected btc-node response creating wallet {wallet}") from error
        if not isinstance(body, dict) or ("error" not in body and "result" not in body):
            raise RpcError(f"Unexpected btc-node response creating wallet {wallet}: {body!r}")
        if body.get("error") is None:
            response.raise_for_status()
        return cast(dict[str, object], body)

    @staticmethod
    def _is_bdb_wallet_creation_error(error: object) -> bool:
        return (
            isinstance(error, dict)
            and error.get("code") == -4
            and isinstance(error.get("message"), str)
            and (
                "BDB wallet creation is deprecated" in cast(str, error["message"])
                or "Compiled without bdb support" in cast(str, error["message"])
            )
        )

    @staticmethod
    def _is_wallet_database_exists_error(error: object) -> bool:
        return (
            isinstance(error, dict)
            and error.get("code") == -4
            and "Database already exists" in str(error.get("message", ""))
        )

    @staticmethod
    def _is_wallet_missing_error(error: Exception) -> bool:
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
