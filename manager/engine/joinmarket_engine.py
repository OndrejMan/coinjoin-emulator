import threading
from time import sleep

from ..wasabi_clients.joinmarket_client import JoinMarketClientServer
from .configuration import ScenarioConfig
from .engine_base import DriverProtocol, EngineArgs, EngineBase
from .joinmarket import (
    JOINMARKET_COINJOIN_AMOUNT_SATS,
    JOINMARKET_COUNTERPARTIES,
    JOINMARKET_DISTRIBUTOR_RPC_WALLET,
    JOINMARKET_FINAL_SETTLE_BLOCKS,
    JOINMARKET_LOOP_SLEEP_SECONDS,
    JOINMARKET_MAKER_MIN_SIZE_SATS,
    JOINMARKET_ROUND_TIMEOUT_BLOCKS,
    joinmarket_container_env,
)
from .joinmarket.events import JoinMarketRoundEventsMixin
from .joinmarket.funding import JoinMarketFundingMixin
from .joinmarket.lifecycle import JoinMarketClientLifecycleMixin
from .joinmarket.rounds import JoinMarketRoundMixin
from .joinmarket.runner import JoinMarketRunnerMixin
from .joinmarket.scenario import default_joinmarket_scenario

__all__ = [
    "JOINMARKET_COINJOIN_AMOUNT_SATS",
    "JOINMARKET_COUNTERPARTIES",
    "JOINMARKET_DISTRIBUTOR_RPC_WALLET",
    "JOINMARKET_FINAL_SETTLE_BLOCKS",
    "JOINMARKET_LOOP_SLEEP_SECONDS",
    "JOINMARKET_MAKER_MIN_SIZE_SATS",
    "JOINMARKET_ROUND_TIMEOUT_BLOCKS",
    "JoinMarketClientServer",
    "JoinmarketEngine",
    "joinmarket_container_env",
    "sleep",
]


class JoinmarketEngine(
    JoinMarketClientLifecycleMixin,
    JoinMarketFundingMixin,
    JoinMarketRoundEventsMixin,
    JoinMarketRoundMixin,
    JoinMarketRunnerMixin,
    EngineBase,
):
    def __init__(self, args: EngineArgs, driver: DriverProtocol) -> None:
        super().__init__(args, driver, "/home/joinmarket")
        self.joinmarket_round_events: list[dict[str, object]] = []
        self._core_wallet_lock = threading.Lock()

    def default_scenario(self) -> ScenarioConfig:
        return default_joinmarket_scenario()

    def init_client(self) -> object:
        return self.init_joinmarket_clientserver(name="joinmarket-client-server", port=28183)

    def init_joinmarket_clientserver(
        self,
        name: str,
        port: int,
        host: str = "localhost",
        role: str = "maker",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
        proxy: str = "",
    ) -> JoinMarketClientServer:
        return JoinMarketClientServer(
            name=name,
            host=host,
            port=port,
            role=role,
            delay=delay,
            stop=stop,
            proxy=proxy,
        )
