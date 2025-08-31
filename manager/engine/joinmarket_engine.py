import backoff

from manager.engine.engine_base import EngineBase
from manager.engine.engine_base import EngineBase
from manager.engine.configuration import ScenarioConfig, WalletConfig, JoinMarketConfig, JoinMarketRole
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer
from time import sleep, time
import sys

class JoinmarketEngine(EngineBase):

    def __init__(self, args, driver):
        super().__init__(args, driver,
                         log_src_path="/home/joinmarket/.joinmarket/logs")

    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig(
            name="default",
            default_version="joinmarket",
            rounds=0,  # the number of coinjoins after which the simulation stops (0 for no limit)
            blocks=0,  # the number of mined blocks after which the simulation stops (0 for no limit)
            wallets=[
                WalletConfig(
                    funds=[75000, 75000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.TAKER,
                        tumbler_options={'addrcount': 3, 'minmakercount': 4, 'makercountrange': [5, 1], 'mixdepthcount': 3, 'mintxcount': 2, 'txcountparams': [3, 1], 'timelambda': 5, 'stage1_timelambda_increase': 1, 'liquiditywait': 60, 'waittime': 20, 'mixdepthsrc': 0, 'restart': True, 'mincjamount': 35000, 'amtmixdepths': 4, 'rounding_chance': 0, 'rounding_sigfig_weights': [55, 15, 25, 65, 45]},
                    ),
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
                WalletConfig(
                    funds=[3000000, 15000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
                WalletConfig(
                    funds=[3000000, 600000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
                WalletConfig(
                    funds=[200000, 50000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
                WalletConfig(
                    funds=[3000000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
                WalletConfig(
                    funds=[3000000, 15000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
                WalletConfig(
                    funds=[3000000, 600000],
                    joinmarket=JoinMarketConfig(
                        role=JoinMarketRole.MAKER,
                        offers=[{'txfee': 0, 'cjfee_a': 5000, 'cjfee_r': 4e-05, 'ordertype': 'sw0reloffer', 'minsize': 30000, 'maxsize': 3000000}],
                    ),
                ),
            ],
        )

    def prepare_images(self):
        print("Preparing images")
        self.prepare_image("btc-node")
        self.prepare_image("joinmarket-client-server")
        self.prepare_image("irc-server")


    def start_engine_infrastructure(self):
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        self.node.create_wallet("jm_wallet")
        print("- created jm_wallet in BitcoinCore")

        self.start_irc_server()
        print("- started irc-server")


    def start_irc_server(self):
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


    def start_distributor(self):
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
        self.distributor = self.init_joinmarket_clientserver(
            name=name,
            port=actual_port,
            host=actual_ip,
            proxy=self.args.proxy
        )

        print(f"- started distributor")


    @staticmethod
    def init_joinmarket_clientserver(name, port, host="localhost", proxy=None):
        print(f"Starting joinmarket-client-server: {name}")
        client = JoinMarketClientServer(name=name, port=port, host=host, proxy=proxy)

        ensure_client_session(client, name)

        if not client.wait_wallet(timeout=30000):
            print(f"- could not start {name} (application timeout)")
            raise Exception("Could not start distributor")
        return client


    def start_client(self, idx: int, wallet: WalletConfig):
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

        sleep(10)
        client = JoinMarketClientServer.from_wallet(
            name=name,
            port=actual_port,
            host=actual_ip,
            wallet=wallet,
            proxy=self.args.proxy)

        print(f"driver starting {name}")
        return client

    def stop_client(self, idx: int):
        name = f"jcs-{idx:03}"
        try:
            self.driver.stop(name)
        except Exception as e:
            print(f"- could not stop client {name}: {e}")

    def store_engine_logs(self, data_path):
        # TODO: store irc logs.
        pass


    def update_coinjoins_joinmarket(self):
        for client in self.clients:
            try:
                delta = client.update(self.current_block, self.current_round)
                # Apply any change in round count; alternatively, have the client trigger an event.
                self.current_round += delta
            except Exception as e:
                print(f"- could not update {client.name} ({e})")


    def run_engine(self):
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")

        try:
            self.update_invoice_payments()
        except Exception as e:
            print(f"- invoice payment update failed: {e}")
        try:
            initial_block = self.node.get_block_count()
        except Exception as e:
            print(f"- could not get initial block count: {e}")
            initial_block = 0
        for i in range(5):
            # Takers need 3 confirmations of transactions for the sourcing commitments
            self.node.mine_block()

        print(f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60))

        while (self.scenario.rounds == 0 or self.current_round < self.scenario.rounds) and (
                self.scenario.blocks == 0 or self.current_block < self.scenario.blocks):
            # refresh block count
            for _ in range(3):
                try:
                    self.current_block = self.node.get_block_count() - initial_block  # type: ignore
                    break
                except Exception as e:
                    print(f"- could not get blocks".ljust(60), end="\r")
                    print(f"Block exception: {e}", file=sys.stderr)
            # safe updates
            try:
                self.update_invoice_payments()
            except Exception as e:
                print(f"- invoice update failed: {e}")
            try:
                self.update_coinjoins_joinmarket()
            except Exception as e:
                print(f"- coinjoin update failed: {e}")
            print(
                f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60),
                end="\r",
            )
            sleep(1)

        print()
        print(f"- limit reached")
        sleep(60)
        self.node.mine_block()

@backoff.on_exception(backoff.expo, Exception, max_tries=5)
def ensure_client_session(client, name):
    if not client.session():
        print(f"- could not start {name} (session timeout)")
        raise Exception("Could not start distributor")