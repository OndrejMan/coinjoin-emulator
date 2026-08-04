"""Wallet lifecycle: creation, unlocking, balances and addresses."""

# The sibling methods are declared under TYPE_CHECKING, so pylint cannot see
# that they return a value.
# pylint: disable=assignment-from-no-return

from collections.abc import Callable
from time import sleep, time
from typing import TYPE_CHECKING, cast

from manager.exceptions import RpcError

from .types import BTC, DEFAULT_WAIT_WALLET_TIMEOUT, PASSWORD, WALLET_TYPE, JsonDict


class JoinMarketWalletMixin:
    """Creates and unlocks the wallet and reads balances, addresses and UTXOs."""

    name: str
    host: str
    port: int
    walletname: str
    seedphrase: str
    has_fidelity_bonds: bool
    _wait_wallet_start: float

    if TYPE_CHECKING:
        # pylint: disable=unused-argument  # these are stub signatures
        def _rpc(
            self,
            method: str,
            endpoint: str,
            json_data: JsonDict | None = None,
            timeout: int = 60,
            repeat: int = 4,
        ) -> JsonDict: ...

        async def _rpc_async(
            self,
            method: str,
            endpoint: str,
            json_data: JsonDict | None = None,
            timeout: int = 60,
            repeat: int = 4,
        ) -> JsonDict: ...

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
            print(
                f"- trying wallet creation for {self.walletname} on {self.host}:{self.port} "
                f"(elapsed {elapsed}s, type: {wallet_type})"
            )
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
            print(
                f"[TIMEOUT] Wallet {self.walletname} not ready after "
                f"{int(time() - self._wait_wallet_start)}s on {self.host}:{self.port}"
            )
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
            raise RpcError(f"Could not retrieve available balance: {e}") from e

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
            raise RpcError(f"Could not retrieve available balance: {e}") from e

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
