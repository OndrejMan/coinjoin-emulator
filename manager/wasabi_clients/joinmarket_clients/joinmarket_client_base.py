import asyncio

import httpx
import urllib3

from .bonds import JoinMarketFidelityBondMixin
from .coins import JoinMarketCoinsMixin
from .maker import JoinMarketMakerMixin
from .rpc import JoinMarketRpcMixin
from .taker import JoinMarketTakerMixin
from .types import (
    WALLET_NAME,
    BondRecord,
    JsonDict,
)
from .wallet import JoinMarketWalletMixin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)




class JoinMarketClientServer(
    JoinMarketRpcMixin,
    JoinMarketWalletMixin,
    JoinMarketTakerMixin,
    JoinMarketMakerMixin,
    JoinMarketCoinsMixin,
    JoinMarketFidelityBondMixin,
):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 28183,
        walletname: str = WALLET_NAME,
        name: str = "joinmarket-client-server",
        proxy: str = "",
        version: str = "",
        type: str = "maker",  # pylint: disable=redefined-builtin  # part of the client API
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
        # Track created bonds: {address: {amount, locktime, creation_block}}
        self.fidelity_bonds: dict[str, BondRecord] = {}
        # Producer-owned ground truth: one record per coinjoin this client starts.
        self.round_events: list[JsonDict] = []

        # Async HTTP client setup
        self._async_client: httpx.AsyncClient | None = None
        self._unlock_lock: asyncio.Lock | None = None  # Will be created when needed
        self._client_initialized = False







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
