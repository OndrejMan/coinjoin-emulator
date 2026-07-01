import json
from time import monotonic, sleep
from typing import cast

import requests

from manager import log_output as log

from .exceptions import RpcError

WALLET = "wallet"
FUNDING_WALLET_TX_FEE = 0.0001


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

    def _response_body(self, response: requests.Response) -> dict[str, object] | None:
        try:
            body = response.json()
        except ValueError:
            return None
        if isinstance(body, dict):
            return body
        return None

    def _rpc_error(self, method: object, wallet: str | None, error: object) -> RpcError:
        wallet_detail = f" wallet={wallet}" if wallet else ""
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            return RpcError(f"Bitcoin Core RPC {method}{wallet_detail} failed: code={code} message={message}")
        return RpcError(f"Bitcoin Core RPC {method}{wallet_detail} failed: {error}")

    def _rpc(self, request: dict[str, object], wallet: str | None = None) -> object:
        request["jsonrpc"] = "1.0"
        request["id"] = "1"
        method = request.get("method")
        wallet_path = f"/wallet/{wallet}" if wallet else ""
        response = requests.post(
            f"http://{self.host}:{self.port}{wallet_path}",
            data=json.dumps(request),
            auth=("user", "password"),
            proxies={"http": self.proxy},
            timeout=5,
        )
        response_body = self._response_body(response)
        if response_body is not None and response_body.get("error") is not None:
            raise self._rpc_error(method, wallet, response_body["error"])
        response.raise_for_status()
        if response_body is None:
            raise RpcError(f"Unexpected Bitcoin Core RPC {method} response: {response.text}")
        if "error" not in response_body and "result" not in response_body:
            raise RpcError(f"Unexpected Bitcoin Core RPC {method} response: {response_body}")
        return response_body["result"]

    def get_block_count(self) -> int:
        request: dict[str, object] = {
            "method": "getblockcount",
            "params": [],
        }
        return cast(int, self._rpc(request))

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
        address = cast(str, self._rpc(request, WALLET))

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

    def wait_ready(self, timeout: int = 300) -> None:
        deadline = monotonic() + timeout
        last_error = None
        last_block_count = None

        while monotonic() < deadline:
            try:
                block_count = self.get_block_count()
                last_block_count = block_count
                if block_count > 200:
                    self.ensure_funding_wallet_ready()
                    break
            except (requests.exceptions.RequestException, RpcError) as exc:
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

    def ensure_funding_wallet_ready(self) -> None:
        loaded_wallets = cast(list[str], self._rpc({"method": "listwallets", "params": []}))
        if WALLET not in loaded_wallets:
            try:
                self._rpc({"method": "loadwallet", "params": [WALLET]})
            except RpcError as exc:
                if self._is_wallet_already_loaded_error(exc):
                    pass
                elif self._is_wallet_missing_error(exc):
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
        response_body = self._post_create_wallet_request(
            wallet, descriptors=False, disable_private_keys=disable_private_keys
        )
        error = response_body.get("error")
        if error is not None and allow_descriptor_fallback and self._is_bdb_wallet_creation_error(error):
            response_body = self._post_create_wallet_request(
                wallet, descriptors=True, disable_private_keys=disable_private_keys
            )
            error = response_body.get("error")

        if error is not None:
            log.error(response_body)
            raise RpcError(str(error))
        log.debug(response_body)

    def _post_create_wallet_request(
        self, wallet: str, descriptors: bool, disable_private_keys: bool = False
    ) -> dict[str, object]:
        try:
            response = requests.post(
                f"http://{self.host}:{self.port}",
                data=json.dumps(
                    self._create_wallet_request(
                        wallet, descriptors=descriptors, disable_private_keys=disable_private_keys
                    )
                ),
                auth=("user", "password"),
                proxies={"http": self.proxy},
                timeout=5,
            )
        except requests.exceptions.Timeout as exc:
            raise TimeoutError(
                f"btc-node RPC at {self.host}:{self.port} timed out creating wallet {wallet}"
            ) from exc

        response_body = self._response_body(response)
        if response_body is None:
            response.raise_for_status()
            raise RpcError(f"Unexpected btc-node RPC response creating wallet {wallet}: {response_body}")
        if "error" not in response_body and "result" not in response_body:
            raise RpcError(f"Unexpected btc-node RPC response creating wallet {wallet}: {response_body}")
        if response_body.get("error") is not None:
            return response_body
        response.raise_for_status()
        return response_body

    def _is_bdb_wallet_creation_error(self, error: object) -> bool:
        if not isinstance(error, dict):
            return False
        message = error.get("message", "")
        return (
            error.get("code") == -4
            and (
                "BDB wallet creation is deprecated" in message
                or "Compiled without bdb support" in message
            )
        )

    def _is_wallet_already_loaded_error(self, error: Exception) -> bool:
        return "already loaded" in str(error)

    def _is_wallet_missing_error(self, error: Exception) -> bool:
        message = str(error)
        return (
            "Path does not exist" in message
            or "not found" in message
            or "No such file or directory" in message
            or "Wallet file verification failed" in message
        )

    def _create_wallet_request(
        self, wallet: str, descriptors: bool, disable_private_keys: bool = False
    ) -> dict[str, object]:
        return {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "createwallet",
            "params": {"wallet_name": wallet, "descriptors": descriptors, "disable_private_keys": disable_private_keys},
        }
