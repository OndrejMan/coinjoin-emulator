"""HTTPS transport to the jmwalletd RPC endpoint, sync and async."""

import asyncio
import json
from time import sleep
from typing import TYPE_CHECKING, cast

import httpx
import requests

from .types import PASSWORD, JoinmarketConflictException, JsonDict


class JoinMarketRpcMixin:
    """Talks to jmwalletd: retries, token refresh and the async client."""

    host: str
    port: int
    proxy: str
    walletname: str
    token: str
    refresh_token: str
    _async_client: httpx.AsyncClient | None
    _unlock_lock: asyncio.Lock | None

    if TYPE_CHECKING:
        def update_coin_history(self) -> None: ...
        async def update_coin_history_async(self) -> None: ...

    def _ensure_async_client(self) -> httpx.AsyncClient:
        """Initialize the async HTTP client if not already done."""
        if self._async_client is None or self._async_client.is_closed:
            # Configure proxy for httpx (correct syntax)
            proxy_config = self.proxy if self.proxy else None
            
            self._async_client = httpx.AsyncClient(
                base_url=f"https://{self.host}:{self.port}/api/v1",
                verify=False,
                proxy=proxy_config,  # httpx uses 'proxy', not 'proxies'
                timeout=httpx.Timeout(60.0),
                http2=True
            )
            self._client_initialized = True
        return self._async_client

    async def aclose(self) -> None:
        """Close the async HTTP client."""
        if self._async_client and not self._async_client.is_closed:
            await self._async_client.aclose()
            self._async_client = None
            self._client_initialized = False

    def update_status(self) -> JsonDict:
        self.update_coin_history()
        return self.session()

    def _rpc(
        self,
        method: str,
        endpoint: str,
        json_data: JsonDict | None = None,
        timeout: int = 60,
        repeat: int = 4,
    ) -> JsonDict:
        url = f"https://{self.host}:{self.port}/api/v1{endpoint}"
        headers = {}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        response = None
        for attempt in range(repeat):
            try:
                print(f"[RPC] {method} {url} (attempt {attempt+1}/{repeat}) data={json_data} using proxy={self.proxy}")
                response = requests.request(
                    method=method,
                    url=url,
                    json=json_data or {},
                    headers=headers,
                    proxies={"https": self.proxy} if self.proxy else None,
                    timeout=timeout,
                    verify=False,
                )
                print(f"[RPC] Response {response.status_code}: {response.text}")

                if response.status_code == 401:
                    print("[RPC] 401 Unauthorized: Attempting to unlock wallet and retry...")
                    self.unlock_wallet()
                    headers['Authorization'] = f'Bearer {self.token}'
                    continue

                if response.status_code == 409:
                    print(f"[RPC] 409 Conflict: {response.text}")
                    raise JoinmarketConflictException(f"Error {response.status_code}: {response.text}", response)

                if response.status_code >= 400:
                    try:
                        print(response.json())
                        error_message = response.json().get("message", "Unknown error")
                    except json.JSONDecodeError:
                        error_message = response.text
                    print(f"[RPC] Error {response.status_code}: {error_message}")
                    raise Exception(f"Error {response.status_code}: {error_message}")

                return cast(JsonDict, response.json())
            except Exception as e:
                print(f"[RPC ERROR] {method} {url}: {e}")
                if attempt == repeat - 1:
                    raise
                sleep(1)
        if response is not None:
            return cast(JsonDict, response.json())

        raise TimeoutError("timeout")

    async def _rpc_async(
        self,
        method: str,
        endpoint: str,
        json_data: JsonDict | None = None,
        timeout: int = 60,
        repeat: int = 4,
    ) -> JsonDict:
        """Async version of _rpc using httpx.AsyncClient."""
        client = self._ensure_async_client()
        headers = {}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        
        for attempt in range(repeat):
            try:
                print(
                    f"[RPC-ASYNC] {method} {endpoint} (attempt {attempt+1}/{repeat}) "
                    f"data={json_data} using proxy={self.proxy}"
                )
                
                response = await client.request(
                    method=method,
                    url=endpoint,
                    json=json_data or {},
                    headers=headers,
                    timeout=timeout
                )
                print(f"[RPC-ASYNC] Response {response.status_code}: {response.text}")

                if response.status_code == 401:
                    print("[RPC-ASYNC] 401 Unauthorized: Attempting to unlock wallet and retry...")
                    await self.unlock_wallet_async()
                    headers['Authorization'] = f'Bearer {self.token}'
                    continue

                if response.status_code == 409:
                    print(f"[RPC-ASYNC] 409 Conflict: {response.text}")
                    raise JoinmarketConflictException(f"Error {response.status_code}: {response.text}", response)

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        error_message = error_data.get("message", "Unknown error")
                    except Exception:
                        error_message = response.text
                    print(f"[RPC-ASYNC] Error {response.status_code}: {error_message}")
                    response.raise_for_status()

                return cast(JsonDict, response.json())
            except httpx.HTTPStatusError as e:
                print(f"[RPC-ASYNC ERROR] {method} {endpoint}: HTTP {e.response.status_code}")
                if attempt == repeat - 1:
                    raise Exception(f"HTTP Error {e.response.status_code}: {e.response.text}") from e
                await asyncio.sleep(1)
            except Exception as e:
                print(f"[RPC-ASYNC ERROR] {method} {endpoint}: {e}")
                if attempt == repeat - 1:
                    raise
                await asyncio.sleep(1)

        raise Exception("timeout")

    def session(self) -> JsonDict:
        try:
            method = "GET"
            endpoint = "/session"
            response = self._rpc(method, endpoint)
            return response
        except Exception as e:
            print(e)
            return {}

    def unlock_wallet(self, password: str | None = None) -> JsonDict:
        """Unlock an existing wallet using the stored walletname."""
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/unlock"
        json_data: JsonDict = {"password": password or PASSWORD}
        response = self._rpc(method, endpoint, json_data=json_data)
        self.token = str(response.get("token", ""))
        self.refresh_token = str(response.get("refresh_token", ""))
        return response

    async def update_status_async(self) -> JsonDict:
        """Async version of update_status"""
        await self.update_coin_history_async()
        session_response = await self.session_async()
        return session_response

    async def session_async(self) -> JsonDict:
        """Async version of session"""
        try:
            method = "GET"
            endpoint = "/session"
            response = await self._rpc_async(method, endpoint)
            return response
        except Exception as e:
            print(f"Session async error: {e}")
            return {}

    async def unlock_wallet_async(self, password: str | None = None) -> JsonDict:
        """Async unlock of an existing wallet using the stored walletname."""
        # Lazy creation of async lock when needed
        if self._unlock_lock is None:
            self._unlock_lock = asyncio.Lock()
        async with self._unlock_lock:
            method = "POST"
            endpoint = f"/wallet/{self.walletname}/unlock"
            json_data: JsonDict = {"password": password or PASSWORD}
            response = await self._rpc_async(method, endpoint, json_data=json_data)
            self.token = str(response.get("token", ""))
            self.refresh_token = str(response.get("refresh_token", ""))
            return response
