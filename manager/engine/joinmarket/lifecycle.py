"""Start-up and shutdown of the JoinMarket-specific containers."""

from time import sleep
from typing import TYPE_CHECKING, cast

import backoff

from manager.driver import Driver
from manager.engine.configuration import WalletConfig
from manager.engine.engine_base import EmulatorClient, EngineArgs, InvoiceDistributor
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer
from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient


@backoff.on_exception(backoff.expo, Exception, max_tries=5)
def ensure_client_session(client: JoinMarketClientServer, name: str) -> None:
    """Establish the jmwalletd session, retrying while the container boots."""
    if not client.session():
        raise Exception(f"Could not establish session for {name}")


class JoinMarketLifecycleMixin:
    """Brings the IRC server, the distributor, the watcher and the clients up and down."""

    args: EngineArgs
    driver: Driver
    distributor: InvoiceDistributor | None
    obwatch_client: OrderbookWatchClient | None

    if TYPE_CHECKING:
        def prepare_image(self, name: str, path: str | None = None) -> None: ...

    def prepare_images(self) -> None:
        print("Preparing images")
        self.prepare_image("btc-node")
        self.prepare_image("joinmarket-client-server")
        self.prepare_image("irc-server")

    def start_irc_server(self) -> None:
        # TODO: When the container fails to start, the exception is not thrown and it is not recognized.
        name = "irc-server"

        try:
            ip, manager_ports, _ = self.driver.run(
                name,
                f"{self.args.image_prefix}irc-server",
                env={},  # Add any necessary environment variables
                ports={6667: 6667},
                cpu=0.25,
                memory=256,
                service_account="irc-server",
                run_as_user=10000,
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise Exception("Could not start IRC server")

    def start_distributor(self) -> None:
        name = "joinmarket-distributor"
        port = 28183  # Use a specific port for the distributor
        try:
            ip, distributor_node_ports, route = self.driver.run(
                name,
                f"{self.args.image_prefix}joinmarket-client-server",
                env={},  # Add any necessary environment variables
                ports={28183: port},
                cpu=1,
                memory=1024,
                service_account="joinmarket"
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise Exception("Could not start distributor")

        actual_port = port if self.args.proxy else (443 if route else distributor_node_ports[port])
        actual_ip = ip if self.args.proxy or self.args.in_cluster else (route if route else self.args.control_ip)

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
                f"{self.args.image_prefix}joinmarket-client-server",
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
            raise Exception("Could not start orderbook watcher")

        # Determine how to reach the service from the controller
        actual_port = 62601 if self.args.proxy else (443 if route else obwatch_ports[port])
        actual_ip = ip if self.args.proxy or self.args.in_cluster else (route if route else self.args.control_ip)

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
            raise Exception("Could not start distributor")
        return client

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> EmulatorClient | None:
        name = f"jcs-{idx:03}"
        port = 28184 + idx
        try:
            print(f"Starting joinmarket-client-server: {name}")
            ip, client_node_ports, route = self.driver.run(
                name,
                f"{self.args.image_prefix}joinmarket-client-server",
                env={},
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
        actual_port = 28183 if self.args.proxy else (443 if route else port)
        actual_ip = ip if self.args.proxy or self.args.in_cluster else (route if route else self.args.control_ip)

        print(f"- started {name} at {actual_ip}:{actual_port}")

        sleep(30)
        if wallet is None:
            raise ValueError("wallet configuration is required to start a JoinMarket client")
        client = JoinMarketClientServer.from_wallet(
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
