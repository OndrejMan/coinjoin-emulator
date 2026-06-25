from .maker import JoinMarketMakerMixin
from .rpc import JoinMarketRpcMixin
from .taker import JoinMarketTakerMixin
from .types import WALLET_NAME
from .wallet import JoinMarketWalletMixin


class JoinMarketClientServer(
    JoinMarketWalletMixin,
    JoinMarketMakerMixin,
    JoinMarketTakerMixin,
    JoinMarketRpcMixin,
):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 28183,
        walletname: str = WALLET_NAME,
        name: str = "joinmarket-client-server",
        proxy: str = "",
        version: str = "",
        role: str = "maker",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
    ) -> None:
        self.host = host
        self.port = port
        self.walletname = walletname  # Store walletname as an instance variable
        self.name = name
        self.proxy = proxy
        self.version = version
        self.role = role
        self.maker_running = False
        self.coinjoin_in_process = False
        self.coinjoin_start = 0
        self.delay = delay
        self.stop = stop
        self.token = ""
        self.refresh_token = ""

    @property
    def type(self) -> str:
        return self.role

    @type.setter
    def type(self, role: str) -> None:
        self.role = role
