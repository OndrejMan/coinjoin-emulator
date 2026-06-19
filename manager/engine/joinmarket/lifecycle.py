import threading
from time import time
from typing import Callable, Protocol

from manager import log_output as log

from ...btc_node import BtcNode
from ...exceptions import CoinjoinEmulatorError, StartupError
from ...wasabi_clients.joinmarket_client import JoinMarketClientServer
from ..configuration import WalletConfig
from ..engine_base import DriverProtocol, EmulatorClient, EngineArgs, InvoiceDistributor
from .constants import JOINMARKET_DISTRIBUTOR_RPC_WALLET
from .environment import joinmarket_container_env


class JoinMarketClientServerFactory(Protocol):
    def __call__(
        self,
        name: str,
        port: int,
        host: str = "localhost",
        role: str = "maker",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
        proxy: str = "",
    ) -> JoinMarketClientServer: ...


class PrepareImage(Protocol):
    def __call__(
        self,
        name: str,
        path: str | None = None,
        local_build: bool | None = None,
    ) -> None: ...


class JoinMarketClientLifecycleMixin:
    args: EngineArgs
    driver: DriverProtocol
    node: BtcNode | None
    distributor: InvoiceDistributor | None
    clients: list[EmulatorClient]
    _core_wallet_lock: threading.Lock
    prepare_image: PrepareImage
    image_ref: Callable[[str], str]
    init_joinmarket_clientserver: JoinMarketClientServerFactory

    def prepare_images(self) -> None:
        log.info("Preparing images")
        self.prepare_image("btc-node")
        self.prepare_image("joinmarket-client-server")
        self.prepare_image("irc-server")

    def start_engine_infrastructure(self) -> None:
        self.start_irc_server()
        log.info("- started irc-server")

    def core_wallet_name(self, client_name: str) -> str:
        return f"jm_wallet_{client_name.replace('-', '_')}"

    def _create_joinmarket_core_wallet(self, wallet_name: str) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")

        with self._core_wallet_lock:
            self.node.create_wallet(
                wallet_name,
                disable_private_keys=True,
            )
        log.info(f"- created {wallet_name} in BitcoinCore")

    def start_irc_server(self) -> None:
        name = "irc-server"

        try:
            self.driver.run(
                name,
                self.image_ref("irc-server"),
                env={},
                ports={6667: 6667},
                cpu=1.0,
                memory=2048,
            )
        except (CoinjoinEmulatorError, RuntimeError, OSError) as e:
            log.error(f"- could not start {name} ({e})")
            raise StartupError("Could not start IRC server") from e

    def _dump_container_log(self, container_name: str, log_path: str) -> None:
        try:
            log_content = self.driver.logs(container_name)
            log.debug(f"- {container_name} container logs:\n{log_content}")
        except (CoinjoinEmulatorError, RuntimeError, OSError):
            log.warning(f"- could not retrieve container logs from {container_name}")

        try:
            log_content = self.driver.peek(container_name, log_path)
            log.debug(f"- {container_name} log ({log_path}):\n{log_content}")
        except (CoinjoinEmulatorError, RuntimeError, OSError):
            log.warning(f"- could not retrieve {log_path} from {container_name}")

    def start_distributor(self) -> None:
        name = "joinmarket-distributor"
        port = 28183
        self._create_joinmarket_core_wallet(JOINMARKET_DISTRIBUTOR_RPC_WALLET)
        try:
            ip, manager_ports = self.driver.run(
                name,
                self.image_ref("joinmarket-client-server"),
                env=joinmarket_container_env(
                    self.args,
                    JOINMARKET_DISTRIBUTOR_RPC_WALLET,
                ),
                ports={28183: port},
                cpu=1.0,
                memory=2048,
            )
        except (CoinjoinEmulatorError, RuntimeError, OSError) as e:
            log.error(f"- could not start {name} ({e})")
            raise StartupError("Could not start distributor") from e

        self.distributor = self.init_joinmarket_clientserver(
            name=name,
            host=ip if self.args.proxy else self.args.control_ip,
            port=28183 if self.args.proxy else manager_ports[28183],
            proxy=self.args.proxy,
        )

        start = time()
        if not self.distributor.wait_wallet(timeout=180):
            elapsed = time() - start
            log.error(f"- could not start {name} (application timeout after {elapsed:.1f}s)")
            self._dump_container_log(name, "/home/joinmarket/jmwalletd.log")
            raise StartupError("Could not start distributor")
        log.info(f"- started distributor (wait took {time() - start:.1f}s)")

    def init_client(self) -> object:
        raise NotImplementedError("JoinMarket clients require init_joinmarket_clientserver()")

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> JoinMarketClientServer | None:
        if wallet is None:
            raise ValueError("wallet configuration is required to start a JoinMarket client")

        name = f"jcs-{idx:03}"
        port = 28184 + idx
        core_wallet = self.core_wallet_name(name)
        self._create_joinmarket_core_wallet(core_wallet)
        try:
            ip, manager_ports = self.driver.run(
                name,
                self.image_ref("joinmarket-client-server"),
                env=joinmarket_container_env(self.args, core_wallet),
                ports={28183: port},
                cpu=0.1,
                memory=768,
            )
        except (CoinjoinEmulatorError, RuntimeError, OSError) as e:
            log.warning(f"- could not start {name} ({e})")
            return None

        log.debug(f"driver starting {name}")

        delay = (wallet.delay_blocks or 0, wallet.delay_rounds or 0)
        stop = (wallet.stop_blocks or 0, wallet.stop_rounds or 0)
        joinmarket_config = wallet.joinmarket
        role_str = joinmarket_config.role.value if joinmarket_config and joinmarket_config.role else "maker"

        client = self.init_joinmarket_clientserver(
            name=name,
            host=ip if self.args.proxy else self.args.control_ip,
            port=28183 if self.args.proxy else manager_ports[28183],
            role=role_str,
            delay=delay,
            stop=stop,
            proxy=self.args.proxy,
        )

        start = time()
        if not client.wait_wallet(timeout=120):
            elapsed = time() - start
            log.warning(f"- could not start {name} (application timeout {elapsed:.1f}s)")
            self._dump_container_log(name, "/home/joinmarket/jmwalletd.log")
            return None

        log.info(f"- started {client.name} (wait took {time() - start} seconds)")
        return client

    def stop_client(self, idx: int) -> None:
        name = f"jcs-{idx:03}"
        self.driver.stop(name)

    def validate_clients(self) -> None:
        takers = [client for client in self.clients if client.type == "taker"]
        makers = [client for client in self.clients if client.type == "maker"]
        if not takers:
            raise RuntimeError("JoinMarket scenario requires at least one started taker client")
        if not makers:
            raise RuntimeError("JoinMarket scenario requires at least one started maker client")
