import asyncio
import json
from time import sleep, time
from typing import cast

import httpx
import requests
import urllib3

from manager.engine.configuration import WalletConfig

from .bonds import JoinMarketFidelityBondMixin
from .coins import JoinMarketCoinsMixin
from .maker import JoinMarketMakerMixin
from .taker import JoinMarketTakerMixin
from .types import (
    PASSWORD,
    WALLET_NAME,
    BondRecord,
    JoinmarketConflictException,
    JsonDict,
)
from .wallet import JoinMarketWalletMixin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)




class JoinMarketClientServer(JoinMarketWalletMixin, JoinMarketTakerMixin, JoinMarketMakerMixin, JoinMarketCoinsMixin, JoinMarketFidelityBondMixin):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 28183,
        walletname: str = WALLET_NAME,
        name: str = "joinmarket-client-server",
        proxy: str = "",
        version: str = "",
        type: str = "maker",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
        offers: list[dict[str, object]] | None = None,
        tumbler_options: dict[str, object] | None = None,
        time_between_rounds: int = 0,
        has_fidelity_bonds: bool = False,
        max_coinjoins: int = 0,
    ) -> None:
        self.host = host
        self.port = port
        self.walletname = walletname  # Store walletname as an instance variable
        self.name = name
        self.proxy = proxy
        self.version = version
        self.type = type
        self.maker_running = False
        self.coinjoin_in_process = False
        self.coinjoin_start = 0
        self.next_coinjoin_allowed = delay[0]
        self.time_between_rounds = time_between_rounds
        self.stop = stop
        self.token = ""
        self.refresh_token = ""
        self.offers = offers if offers else []
        self.tumbler_options = tumbler_options if tumbler_options else None
        self.coin_history: dict[str, JsonDict] = {}
        self.seedphrase = ""
        self.has_fidelity_bonds = has_fidelity_bonds
        self.max_coinjoins = max_coinjoins
        self.completed_coinjoins = 0

        # Fidelity bond tracking
        self.fidelity_bonds: dict[str, BondRecord] = {}  # Track created bonds: {address: {amount, locktime, creation_block}}
        # Producer-owned ground truth: one record per coinjoin this client starts.
        self.round_events: list[JsonDict] = []

        # Async HTTP client setup
        self._async_client: httpx.AsyncClient | None = None
        self._unlock_lock: asyncio.Lock | None = None  # Will be created when needed
        self._client_initialized = False

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

    @classmethod
    def from_wallet(
        cls,
        name: str,
        port: int,
        wallet: WalletConfig,
        host: str,
        proxy: str = "",
    ) -> "JoinMarketClientServer | None":
        joinmarket = getattr(wallet, "joinmarket", None)
        type_ = joinmarket.role.value if joinmarket and joinmarket.role else "maker"
        tumbler_options = (joinmarket.tumbler_options if joinmarket else None) or {}

        # Check if wallet has fidelity bonds configured
        fidelity_bond = (joinmarket.fidelity_bond if joinmarket else None) or {}
        has_fidelity_bonds = bool(fidelity_bond.get("enabled", False))

        # Select the appropriate subclass based on wallet config.
        client_cls: type["JoinMarketClientServer"]
        if type_ == "maker":
            from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import MakerClient
            client_cls = MakerClient
        elif type_ == "taker":
            # Distinguish between a standard taker and a tumbler taker based on tumbler_options.
            if tumbler_options:
                from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import TumblerTakerClient
                client_cls = TumblerTakerClient
            else:
                from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import TakerClient
                client_cls = TakerClient
        else:
            client_cls = cls

        # Instantiate the client using the selected subclass.
        client = client_cls(
            name=name,
            port=port,
            type=type_,
            delay=(wallet.delay_blocks or 0, wallet.delay_rounds or 0),
            stop=(wallet.stop_blocks or 0, wallet.stop_rounds or 0),
            offers=(joinmarket.offers if joinmarket else None) or [],
            tumbler_options=tumbler_options,
            time_between_rounds=(joinmarket.time_between_rounds if joinmarket else 0) or 0,
            has_fidelity_bonds=has_fidelity_bonds,
            max_coinjoins=int(cast(int, (joinmarket.max_coinjoins if joinmarket else None) or 0)),
            host=host,
            proxy=proxy
        )

        start = time()
        if not client.wait_wallet(timeout=120):
            print(
                f"- could not start {name} (application timeout {time() - start} seconds)"
            )
            return None

        print(f"- started {client.name} (wait took {time() - start} seconds)")
        return client

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
                    proxies=dict(https=self.proxy) if self.proxy else None,
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
                print(f"[RPC-ASYNC] {method} {endpoint} (attempt {attempt+1}/{repeat}) data={json_data} using proxy={self.proxy}")
                
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
                    raise Exception(f"HTTP Error {e.response.status_code}: {e.response.text}")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"[RPC-ASYNC ERROR] {method} {endpoint}: {e}")
                if attempt == repeat - 1:
                    raise
                await asyncio.sleep(1)

        raise Exception("timeout")

    def update(self, current_block: int, current_round: int) -> int:
        """Advance this client one engine tick; returns the change in round count."""
        raise NotImplementedError

    async def update_async(self, current_block: int, current_round: int) -> int:
        """Async counterpart of update()."""
        raise NotImplementedError

    def is_paused(self, current_block: int) -> bool:
        # Check delay - "delay[0]" means "don't run until current_block >= delay[0]"
        if current_block < self.next_coinjoin_allowed:
            return True
        # Check max coinjoins limit
        if self.max_coinjoins > 0 and self.completed_coinjoins >= self.max_coinjoins:
            return True
        return False



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
































