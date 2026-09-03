"""Start-up and shutdown of the JoinMarket-specific containers."""

import threading
from time import sleep
from typing import TYPE_CHECKING, cast

import backoff

from manager.driver import Driver
from manager.engine.base.protocols import EmulatorClient, EngineArgs, InvoiceDistributor
from manager.engine.configuration import WalletConfig
from manager.engine.joinmarket.environment import joinmarket_container_env
from manager.exceptions import StartupError
from manager.wasabi_clients.joinmarket_clients.factory import client_from_wallet
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer
from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient


@backoff.on_exception(backoff.expo, Exception, max_tries=5)
def ensure_client_session(client: JoinMarketClientServer, name: str) -> None:
    """Establish the jmwalletd session, retrying while the container boots."""
    if not client.session():
        raise StartupError(f"Could not establish session for {name}")


class JoinMarketLifecycleMixin:
    """Brings the IRC server, the distributor, the watcher and the clients up and down."""

    args: EngineArgs
    driver: Driver
    distributor: InvoiceDistributor | None
    obwatch_client: OrderbookWatchClient | None
    clients: list[EmulatorClient]
    _core_wallet_lock: threading.Lock

    if TYPE_CHECKING:
        # pylint: disable=unused-argument  # these are stub signatures
        def prepare_image(self, name: str, path: str | None = None) -> None: ...
        def image_ref(self, name: str) -> str: ...
        def service_endpoint(
            self, ip: str, container_port: int, ports: dict[int, int], route: object = None
        ) -> tuple[str, int]:
            return ip, container_port

    def prepare_images(self) -> None:
        print("Preparing images")
        self.prepare_image("btc-node")
        self.prepare_image("joinmarket-client-server")
        self.prepare_image("irc-server")

    @staticmethod
    def core_wallet_name(client_name: str) -> str:
        return f"jm_wallet_{client_name.replace('-', '_')}"

    def _create_joinmarket_core_wallet(self, wallet_name: str) -> None:
        node = getattr(self, "node", None)
        if node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        with self._core_wallet_lock:
            node.create_wallet(wallet_name, disable_private_keys=True)
        print(f"- created {wallet_name} in BitcoinCore")

    def start_irc_server(self) -> None:
        # TODO: When the container fails to start, the exception is not thrown and it is not recognized.
        name = "irc-server"

        try:
            _, _, _ = self.driver.run(
                name,
                self.image_ref("irc-server"),
                env={},  # Add any necessary environment variables
                ports={6667: 6667},
                cpu=0.25,
                memory=256,
                service_account="irc-server",
                run_as_user=10000,
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise StartupError("Could not start IRC server") from e

    def start_distributor(self) -> None:
        name = "joinmarket-distributor"
        port = 28183  # Use a specific port for the distributor
        core_wallet = self.core_wallet_name(name)
        self._create_joinmarket_core_wallet(core_wallet)
        try:
            ip, distributor_node_ports, route = self.driver.run(
                name,
                self.image_ref("joinmarket-client-server"),
                env=joinmarket_container_env(self.args, core_wallet),
                ports={28183: port},
                cpu=1,
                memory=1024,
                service_account="joinmarket"
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise StartupError("Could not start distributor") from e

        actual_ip, actual_port = self.service_endpoint(ip, port, distributor_node_ports, route)

        print(f"- started {name} at {actual_ip}:{actual_port}")
        self.distributor = cast(InvoiceDistributor, self.init_joinmarket_clientserver(
            name=name,
            port=actual_port,
            host=str(actual_ip),
            proxy=self.args.proxy,
        ))

        print("- started distributor")

    def start_orderbook_watch(self) -> None:
        name = "joinmarket-obwatch"
        port = 62601
        try:
            ip, obwatch_ports, route = self.driver.run(
                name,
                self.image_ref("joinmarket-client-server"),
                env={"MODE": "obwatch"},
                ports={62601: port},
                cpu=0.25,
                memory=256,
                service_account="joinmarket",
                run_as_user=1000,
                run_as_group=1000,
                proxy=self.args.proxy
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise StartupError("Could not start orderbook watcher") from e

        # Determine how to reach the service from the controller
        actual_ip, actual_port = self.service_endpoint(ip, 62601, obwatch_ports, route)

        print(f"- started {name} at {actual_ip}:{actual_port}")

        # Attach a lightweight client that periodically polls and stores snapshots under /tmp
        ob_client = OrderbookWatchClient(
            name=name,
            host=actual_ip,
            port=actual_port,
            type="orderbook",
        )
        self.obwatch_client = ob_client

    @staticmethod
    def init_joinmarket_clientserver(
        name: str,
        port: int,
        host: str = "localhost",
        proxy: str | None = None,
    ) -> JoinMarketClientServer:
        print(f"Starting joinmarket-client-server: {name}")
        client = JoinMarketClientServer(name=name, port=port, host=host, proxy=proxy or "")

        ensure_client_session(client, name)

        if not client.wait_wallet(timeout=120):
            print(f"- could not start {name} (application timeout)")
            raise StartupError("Could not start distributor")
        return client

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> EmulatorClient | None:
        name = f"jcs-{idx:03}"
        port = 28184 + idx
        core_wallet = self.core_wallet_name(name)
        self._create_joinmarket_core_wallet(core_wallet)
        try:
            print(f"Starting joinmarket-client-server: {name}")
            ip, client_ports, route = self.driver.run(
                name,
                self.image_ref("joinmarket-client-server"),
                env=joinmarket_container_env(self.args, core_wallet),
                ports={28183: port},
                cpu=(0.05),
                memory=(64),
                service_account="joinmarket",
                run_as_user=1000,
                run_as_group=1000,
                proxy=self.args.proxy
            )
            print(f"Started joinmarket-client-server: {name}")
        except Exception as e:
            print(f"- error starting {name}: {e}")
            return None

        # In kubernetes, the pod is addressed using the ip unique for that service and all pods have the port
        # 28183 in use. The port rotation is needed for the local docker run, where the ports are mapped to the local
        # host. Only the driver knows the reachable port: docker and podman echo the requested rotation back, while
        # kubernetes allocates a NodePort that has nothing to do with it.
        actual_ip, actual_port = self.service_endpoint(ip, 28183, client_ports or {28183: port}, route)

        print(f"- started {name} at {actual_ip}:{actual_port}")

        sleep(30)
        if wallet is None:
            raise ValueError("wallet configuration is required to start a JoinMarket client")
        client = client_from_wallet(
            name=name,
            port=actual_port,
            host=str(actual_ip),
            wallet=wallet,
            proxy=self.args.proxy or "",
        )

        print(f"driver starting {name}")
        return cast(EmulatorClient | None, client)

    def stop_client(self, idx: int) -> None:
        name = f"jcs-{idx:03}"
        try:
            self.driver.stop(name)
        except Exception as e:
            print(f"- could not stop client {name}: {e}")

    def validate_clients(self) -> None:
        super().validate_clients()  # type: ignore[misc]  # supplied by EngineBase's client mixin
        roles = {getattr(client, "type", "") for client in self.clients}
        if "taker" not in roles:
            raise RuntimeError("JoinMarket scenario requires at least one started taker client")
        if "maker" not in roles:
            raise RuntimeError("JoinMarket scenario requires at least one started maker client")
