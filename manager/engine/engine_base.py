import multiprocessing
import multiprocessing.pool
import os
import time

from manager.btc_node import BtcNode
from manager.driver import Driver
from manager.engine.base.clients import EngineClientsMixin
from manager.engine.base.funding import INITIAL_DISTRIBUTOR_BTC, EngineFundingMixin
from manager.engine.base.logs import EngineLogsMixin
from manager.engine.base.protocols import EmulatorClient, EngineArgs, InvoiceDistributor
from manager.engine.configuration import ScenarioConfig, WalletConfig


def int_env(name: str) -> int | None:
    """Read a positive integer id from the environment, ignoring unusable values.

    Root (0) is skipped on purpose: pods declare ``runAsNonRoot`` and a root
    caller can read the shared datadir whatever owns it.
    """
    raw = os.environ.get(name, "").strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if value > 0 else None


class EngineBase(EngineClientsMixin, EngineFundingMixin, EngineLogsMixin):
    def __init__(self, args: EngineArgs, driver: Driver, log_src_path: str) -> None:
        self.args = args
        self.driver = driver
        self.log_src_path = log_src_path
        self.scenario: ScenarioConfig = self.default_scenario()
        self.versions: set[str] = set()
        self.node: BtcNode | None = None
        self.distributor: InvoiceDistributor | None = None
        self.clients: list[EmulatorClient] = []
        self.invoices: dict[tuple[int, int], list[tuple[str, int]]] = {}
        self.current_block = 0
        self.current_round = 0

    def default_scenario(self) -> ScenarioConfig:
        raise NotImplementedError

    def load_scenario(self) -> None:
        if self.args.command == "run" and self.args.scenario:
            self.scenario = ScenarioConfig.from_json_config(self.args.scenario)

        self.scenario.validate_for_engine(getattr(self.args, "engine", "wasabi"))

        self.versions.add(self.scenario.default_version)
        if self.scenario.distributor_version is not None:
            self.versions.add(self.scenario.distributor_version)
        for wallet in self.scenario.wallets:
            if wallet.version is not None:
                self.versions.add(wallet.version)

    def prepare_images(self) -> None:
        raise NotImplementedError

    def image_ref(self, name: str) -> str:
        """Resolve an exact infrastructure image override before the prefix default."""
        override = getattr(self.args, f"{name.replace('-', '_')}_image", "")
        return str(override or f"{self.args.image_prefix}{name}")

    def local_build_requested(self, name: str) -> bool:
        return name in {"btc-node", "joinmarket-client-server", "irc-server"} and bool(
            getattr(self.args, "coinjoin_infrastructure_local_build", False)
        )

    def service_endpoint(
        self,
        ip: str,
        container_port: int,
        ports: dict[int, int],
        route: object = None,
    ) -> tuple[str, int]:
        """Resolve a driver endpoint for local, proxied, in-cluster, and routed runs."""
        if self.args.proxy:
            return ip, container_port
        if self.args.in_cluster or getattr(self.driver, "in_cluster", False):
            # The Kubernetes driver returns a Service DNS name.  Reach it on
            # the Service port, which may intentionally differ from the
            # container's target port (for example 37131 -> 37128 for the
            # Wasabi distributor).
            return ip, ports.get(container_port, container_port)
        if route:
            return str(route), 443
        return self.args.control_ip, ports[container_port]

    def prepare_image(self, name: str, path: str | None = None) -> None:
        image_name = self.image_ref(name)
        has_override = bool(getattr(self.args, f"{name.replace('-', '_')}_image", ""))
        if self.local_build_requested(name):
            self.driver.build(image_name, f"./containers/{name}" if path is None else path)
            print(f"- image built {image_name}")
        elif self.driver.has_image(image_name):
            if self.args.force_rebuild:
                if self.args.image_prefix or has_override:
                    self.driver.pull(image_name)
                    print(f"- image pulled {image_name}")
                else:
                    self.driver.build(name, f"./containers/{name}" if path is None else path)
                    print(f"- image rebuilt {image_name}")
            else:
                print(f"- image reused {image_name}")
        elif self.args.image_prefix or has_override:
            self.driver.pull(image_name)
            print(f"- image pulled {image_name}")
        else:
            self.driver.build(name, f"./containers/{name}" if path is None else path)
            print(f"- image built {image_name}")

    def start_infrastructure(self) -> None:
        print("Starting infrastructure")
        self.start_btc_node()
        self.start_engine_infrastructure()
        self.start_distributor()

    def start_btc_node(self) -> None:
        node_volumes = None
        # bitcoind creates <datadir>/regtest with mode 0700, so the image's own
        # user (100:101) would leave the shared datadir unreadable for whoever
        # runs the analysis afterwards. Run the node as the storage identity of
        # the caller when the datadir is a shared host path.
        storage_uid = None
        storage_gid = None
        if self.args.btcFolder:
            absolute_host_path = os.path.abspath(self.args.btcFolder)
            mount = {"bind": "/home/bitcoin/data", "mode": "rw"}
            node_volumes = {absolute_host_path: mount}
            storage_uid = int_env("KUBERNETES_STORAGE_UID")
            storage_gid = int_env("KUBERNETES_STORAGE_GID") if storage_uid else None

        command = ["./run.sh", *self.args.btc_node_arg] if self.args.btc_node_arg else None
        btc_node_env: dict[str, str] = {}
        initial_block_count = os.environ.get("COINJOIN_BTC_NODE_INITIAL_BLOCK_COUNT")
        if initial_block_count:
            btc_node_env["COINJOIN_INITIAL_BLOCK_COUNT"] = initial_block_count
        btc_node_ip, btc_node_ports, route = self.driver.run(
            "btc-node",
            self.image_ref("btc-node"),
            ports={18443: 18443, 18444: 18444},
            cpu=2.0,
            memory=2048,
            service_account="btc-node",
            volumes=node_volumes,
            command=command,
            run_as_user=storage_uid,
            run_as_group=storage_gid,
            env=btc_node_env or None,
        )

        print(btc_node_ip, btc_node_ports)
        node_host, node_port = self.service_endpoint(btc_node_ip, 18443, btc_node_ports, route)
        self.node = BtcNode(
            host=node_host,
            port=node_port,
            internal_ip=btc_node_ip,
            proxy=self.args.proxy,
        )
        print("BTC node startup in progress")
        self.node.wait_ready()
        print("- started btc-node")

    def start_engine_infrastructure(self) -> None:
        raise NotImplementedError

    def start_distributor(self) -> None:
        raise NotImplementedError

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> EmulatorClient | None:
        raise NotImplementedError

    def stop_client(self, idx: int) -> None:
        raise NotImplementedError









    def stop_coinjoins(self) -> None:
        print("Stopping coinjoins")
        
        # Helper function to stop a single client's coinjoin
        def stop_single_client(client: EmulatorClient) -> bool:
            try:
                client.stop_coinjoin()
                print(f"- stopped mixing {client.name}")
                return True
            except Exception as e:
                print(f"- could not stop mixing {client.name}: {e}")
                return False
        
        # Use ThreadPool to parallelize stopping coinjoins
        with multiprocessing.pool.ThreadPool() as pool:
            results = pool.map(stop_single_client, self.clients)
            
        success_count = sum(1 for r in results if r)
        print(f"- stopped mixing for {success_count}/{len(self.clients)} clients")

    def shutdown_engine(self) -> None:
        """Release engine-specific local resources after clients have stopped."""




    
    def run(self) -> None:
        print(f"=== Scenario {self.scenario.name} ===")
        if not getattr(self.args, "no_logs", False):
            self.ensure_log_run_path_available()
        self.prepare_images()
        self.start_infrastructure()
        self.fund_distributor(INITIAL_DISTRIBUTOR_BTC)
        self.start_clients(self.scenario.wallets)
        self.validate_clients()
        time.sleep(60)
        self.prepare_invoices(self.scenario.wallets)

        # Pay initial wallet funding invoices before additional funding
        print("Paying initial wallet funding")
        self.update_invoice_payments()

        # Allow engines to perform additional post-funding setup (e.g., fidelity bonds)
        self.prepare_additional_funding(self.scenario.wallets)

        print("Running simulation")
        self.run_engine()

    def run_engine(self) -> None:
        raise NotImplementedError
