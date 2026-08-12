import asyncio
import json
from collections.abc import Callable
from time import sleep, time
from typing import cast

import httpx
import requests
import urllib3

from manager.engine.configuration import WalletConfig

from .bonds import JoinMarketFidelityBondMixin
from .coins import JoinMarketCoinsMixin
from .maker import JoinMarketMakerMixin
from .types import (
    BTC,
    DEFAULT_WAIT_WALLET_TIMEOUT,
    PASSWORD,
    WALLET_NAME,
    WALLET_TYPE,
    BondRecord,
    JoinmarketConflictException,
    JsonDict,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)




class JoinMarketClientServer(JoinMarketMakerMixin, JoinMarketCoinsMixin, JoinMarketFidelityBondMixin):
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

    def _create_wallet(self, walletname: str | None = None, wallettype: str | None = None) -> JsonDict:
        """Create a new wallet and store its name."""
        method = "POST"
        endpoint = "/wallet/create"
        walletname = walletname or self.walletname
        wallet_type = wallettype or WALLET_TYPE
        data: JsonDict = {
            "walletname": walletname,
            "password": PASSWORD,
            "wallettype": wallet_type,
        }
        # Use a longer timeout for wallet creation (slow clients)
        response = self._rpc(method, endpoint, json_data=data, timeout=300)
        self.token = str(response.get("token", ""))
        self.refresh_token = str(response.get("refresh_token", ""))
        self.seedphrase = str(response.get("seedphrase", ""))
        return response

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

    async def run_schedule_async(self) -> JsonDict:
        """Async version of run_schedule"""
        if not self.tumbler_options:
            raise Exception("No tumbler options provided")
        address_count = int(cast(int, self.tumbler_options.get("address_count", 3)))
        destination_addresses = [self.get_new_address() for _ in range(address_count)]

        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        json_data: JsonDict = {
            "destination_addresses": destination_addresses,
            "tumbler_options": self.tumbler_options
        }

        start = time()
        while time() - start < 60:  # Using a longer timeout for the more complex tumbler operation
            try:
                response = await self._rpc_async(method, endpoint, json_data=json_data)
                return response
            except Exception:
                if time() - start >= 60:
                    print("Failed to run schedule, attempt timed out.")
                await asyncio.sleep(1)  # Add a small delay between retries

        raise TimeoutError(f"Could not run the tumbler schedule for {self.walletname}")

    async def get_schedule_async(self) -> JsonDict:
        """Async version of get_schedule"""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        response = await self._rpc_async(method, endpoint)
        return response


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

    def _retry_until_deadline(self, step: Callable[[], None], deadline: float) -> None:
        """Retry step with exponential backoff until the deadline passes."""
        delay = 1.0
        while True:
            try:
                step()
                return
            except Exception:
                remaining = deadline - time()
                if remaining <= 0:
                    raise
                sleep(min(delay, remaining))
                delay = min(delay * 2, 8.0)

    def _wait_wallet_create(self, deadline: float) -> None:
        def create() -> None:
            elapsed = int(time() - self._wait_wallet_start)
            wallet_type = "sw-fb" if self.has_fidelity_bonds else WALLET_TYPE
            print(f"- trying wallet creation for {self.walletname} on {self.host}:{self.port} (elapsed {elapsed}s, type: {wallet_type})")
            self._create_wallet(wallettype=wallet_type)

        self._retry_until_deadline(create, deadline)

    def _wait_wallet_display(self, deadline: float) -> None:
        def display() -> None:
            elapsed = int(time() - self._wait_wallet_start)
            print(f"- checking wallet display for {self.walletname} on {self.host}:{self.port} (elapsed {elapsed}s)")
            self.get_balance()
            print(f"- wallet {self.walletname} ready on {self.host}:{self.port}")

        self._retry_until_deadline(display, deadline)

    def wait_wallet(self, timeout: int | None = None) -> bool:
        """
        Wait for the wallet to become available, using separate exponential backoff for creation and display.

        The timeout is the budget for each of the two phases; it used to be
        ignored in favour of a fixed 60 seconds.
        """
        self._wait_wallet_start = time()
        budget = DEFAULT_WAIT_WALLET_TIMEOUT if timeout is None else timeout
        try:
            try:
                self._wait_wallet_create(time() + budget)
            except Exception as e:
                print(f"- wallet {self.walletname} creation failed: {e}")
                raise
            self._wait_wallet_display(time() + budget)
            return True
        except Exception:
            print(f"[TIMEOUT] Wallet {self.walletname} not ready after {int(time() - self._wait_wallet_start)}s on {self.host}:{self.port}")
            return False

    def display_wallet(self) -> JsonDict:
        """Get detailed breakdown of wallet contents by account."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/display"
        response = self._rpc(method, endpoint)
        return response

    async def display_wallet_async(self) -> JsonDict:
        """Async get detailed breakdown of wallet contents by account."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/display"
        response = await self._rpc_async(method, endpoint)
        return response

    def get_balance(self) -> int:
        """Retrieve the available balance of the wallet.
        Returns: str: The available balance as a string in BTC (e.g., '0.00000000').
        Raises: Exception: If the balance information cannot be retrieved.
        """
        response = self.display_wallet()
        try:
            walletinfo = cast(JsonDict, response["walletinfo"])
            return int(float(str(walletinfo["available_balance"])) * BTC)
        except KeyError as e:
            raise Exception(f"Could not retrieve available balance: {e}")

    async def get_balance_async(self) -> int:
        """Async retrieve the available balance of the wallet.
        Returns: str: The available balance as a string in BTC (e.g., '0.00000000').
        Raises: Exception: If the balance information cannot be retrieved.
        """
        response = await self.display_wallet_async()
        try:
            walletinfo = cast(JsonDict, response["walletinfo"])
            return int(float(str(walletinfo["available_balance"])) * BTC)
        except KeyError as e:
            raise Exception(f"Could not retrieve available balance: {e}")


    def get_new_address(self, mixdepth: int = 0) -> str:
        """Get a fresh address in the given account for depositing funds."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/address/new/{mixdepth}"
        response = self._rpc(method, endpoint)
        return str(response["address"])







    def list_utxos(self) -> JsonDict:
        """List details of all UTXOs currently in the wallet."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/utxos"
        response = self._rpc(method, endpoint)
        return response

    async def list_utxos_async(self) -> JsonDict:
        """Async list details of all UTXOs currently in the wallet."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/utxos"
        response = await self._rpc_async(method, endpoint)
        return response





    def record_round_start(
        self,
        destination: str,
        amount_sats: int | None,
        counterparties: int | None,
        mixdepth: int | None,
        current_block: int,
        chain_height: int | None = None,
    ) -> JsonDict:
        """Record a producer-owned round event for later reconciliation with the chain."""
        event = {
            "round_id": len(self.round_events) + 1,
            "engine": "joinmarket",
            "status": "started",
            "taker": self.name,
            "destination_address": destination,
            "amount_sats": amount_sats,
            "counterparties": counterparties,
            "mixdepth": mixdepth,
            "start_block": current_block,
            "start_chain_height": chain_height,
        }
        self.round_events.append(event)
        return event

    def start_coinjoin(
        self,
        mixdepth: int,
        amount_sats: int,
        counterparties: int,
        destination: str,
        txfee: int | None = None,
    ) -> JsonDict:
        """
        Initiate a coinjoin as taker.
        - mixdepth: int, the mixdepth to spend from
        - amount_sats: int, amount in satoshis to coinjoin
        - counterparties: int, number of counterparties to coinjoin with
        - destination: str, address to send the coinjoined funds to
        - txfee: optional, int, Bitcoin miner fee to use for transaction
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/coinjoin"
        json_data: JsonDict = {
            "mixdepth": mixdepth,
            "amount_sats": amount_sats,
            "counterparties": counterparties,
            "destination": destination
        }
        if txfee is not None:
            json_data["txfee"] = txfee
        response = self._rpc(method, endpoint, json_data=json_data)
        return response

    async def start_coinjoin_async(
        self,
        mixdepth: int,
        amount_sats: int,
        counterparties: int,
        destination: str,
        txfee: int | None = None,
    ) -> JsonDict:
        """
        Async initiate a coinjoin as taker.
        - mixdepth: int, the mixdepth to spend from
        - amount_sats: int, amount in satoshis to coinjoin
        - counterparties: int, number of counterparties to coinjoin with
        - destination: str, address to send the coinjoined funds to
        - txfee: optional, int, Bitcoin miner fee to use for transaction
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/coinjoin"
        json_data: JsonDict = {
            "mixdepth": mixdepth,
            "amount_sats": amount_sats,
            "counterparties": counterparties,
            "destination": destination
        }
        if txfee is not None:
            json_data["txfee"] = txfee
        response = await self._rpc_async(method, endpoint, json_data=json_data)
        return response

    def run_schedule(self) -> JsonDict:
        """
        Create and run a schedule of transactions.
        - destination_addresses: list of str, addresses to send funds to
        - tumbler_options: optional, dict, additional tumbler configuration options
        """
        if not self.tumbler_options:
            raise Exception("No tumbler options provided")
        address_count = int(cast(int, self.tumbler_options.get("address_count", 3)))
        destination_addresses = [self.get_new_address() for _ in range(address_count)]

        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        json_data: JsonDict = {
            "destination_addresses": destination_addresses,
            "tumbler_options": self.tumbler_options
        }

        start = time()
        while time() - start < 60:  # Using a longer timeout for the more complex tumbler operation
            try:
                response = self._rpc(method, endpoint, json_data=json_data)
                return response
            except Exception:
                if time() - start >= 60:
                    print("Failed to run schedule, attempt timed out.")
                sleep(1)  # Add a small delay between retries

        raise TimeoutError(f"Could not run the tumbler schedule for {self.walletname}")

    def get_schedule(self) -> JsonDict:
        """Get the schedule that is currently running."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        response = self._rpc(method, endpoint)
        return response

    def stop_coinjoin(self) -> object:
        """Stop a running coinjoin attempt."""
        try:
            if self.type == "taker" and self.coinjoin_in_process:
                return self.stop_taker()
            elif self.type == "maker" and self.maker_running:
                return self.stop_maker()
            else:
                print("No coinjoin in process")
                return True
        except Exception as e:
            print(f"Failed to stop coinjoin: {e}")
            return False

    def stop_taker(self) -> JsonDict:
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/stop"
        # When stopping not running taker, returns 401 response
        response = self._rpc(method, endpoint)
        return response

    def send(self, addressed_fundings: list[tuple[str, int]]) -> None:
        try:
            for address, amount in addressed_fundings:
                self.simple_send(destination_address=address, amount_sats=amount)
                print(f"- sent {amount} sats to {address}")
                sleep(5)  # The btc node needs time to process the transaction
        except Exception as e:
            print(f"- error during fund distribution: {e}")
            raise e


    def simple_send(
        self,
        destination_address: str,
        amount_sats: int,
        mixdepth: int = 0,
        txfee: int = 5000,
    ) -> JsonDict | bool:
        """
        Send funds to a single address without coinjoin.
        - destination_address: str, address to send funds to
        - amount_sats: int, amount in satoshis to send
        - mixdepth: int, the mixdepth to spend from
        - txfee: int, miner fee in satoshis
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/direct-send"
        json_data: JsonDict = {
            "destination": destination_address,
            "amount_sats": amount_sats,
            "txfee": txfee,
            "mixdepth": mixdepth,
        }
        start = time()
        while time() - start < 30:
            try:
                response = self._rpc(method, endpoint, json_data=json_data)
                return response
            except Exception as e:
                print(e)
                sleep(2)

        print("Failed to send funds, attempt timed out.")

        return False










