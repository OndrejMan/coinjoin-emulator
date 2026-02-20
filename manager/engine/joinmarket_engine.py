from manager.engine.engine_base import EngineBase
from manager.engine.configuration import ScenarioConfig, WalletConfig, JoinMarketConfig, JoinMarketRole
from manager.wasabi_clients.joinmarket_client import JoinMarketClientServer
from time import sleep, time
import sys

class JoinmarketEngine(EngineBase):

    def __init__(self, args, driver):
        super().__init__(args, driver, "/home/joinmarket")

    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig(
            name="default",
            default_version="joinmarket",
            rounds=5,  # the number of coinjoins after which the simulation stops (0 for no limit)
            blocks=0,  # the number of mined blocks after which the simulation stops (0 for no limit)
            wallets=[
                WalletConfig(
                    funds=[200000, 50000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.TAKER)
                ),
                WalletConfig(
                    funds=[3000000],
                    delay_blocks=2,
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.TAKER)
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
                ),
                WalletConfig(
                    funds=[3000000, 15000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
                ),
                WalletConfig(
                    funds=[3000000, 600000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
                ),
                WalletConfig(
                    funds=[200000, 50000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
                ),
                WalletConfig(
                    funds=[3000000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
                ),
                WalletConfig(
                    funds=[3000000, 15000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
                ),
                WalletConfig(
                    funds=[1000000, 500000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
                ),
                WalletConfig(
                    funds=[3000000, 600000],
                    joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER)
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
        name = "irc-server"

        try:
            ip, manager_ports = self.driver.run(
                name,
                f"{self.args.image_prefix}irc-server",
                env={},  # Add any necessary environment variables
                ports={6667: 6667},
                cpu=1.0,
                memory=2048,
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise Exception("Could not start IRC server")


    def start_distributor(self):
        name = "joinmarket-distributor"
        port = 28183  # Use a specific port for the distributor
        try:
            ip, manager_ports = self.driver.run(
                name,
                "joinmarket-client-server:latest",
                env={},  # Add any necessary environment variables
                ports={28183: port},
                cpu=1.0,
                memory=2048,
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise Exception("Could not start distributor")

        self.distributor = self.init_joinmarket_clientserver(name=name, port=port)

        start = time()
        if not self.distributor.wait_wallet(timeout=60):
            print(f"- could not start {name} (application timeout)")
            raise Exception("Could not start distributor")
        print(f"- started distributor")


    def init_joinmarket_clientserver(self, name, port, host="localhost", type="maker"):
        return JoinMarketClientServer(name=name, port=port, type=type)


    def start_client(self, idx: int, wallet: WalletConfig):
        name = f"jcs-{idx:03}"
        port = 28184 + idx
        try:
            ip, manager_ports = self.driver.run(
                name,
                "joinmarket-client-server:latest",
                env={},
                ports={28183: port},
                cpu=(0.1),
                memory=(768),
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            return None

        print(f"driver starting {name}")

        delay = (wallet.delay_blocks or 0, wallet.delay_rounds or 0)
        stop = (wallet.stop_blocks or 0, wallet.stop_rounds or 0)
        
        # Get JoinMarket role
        joinmarket_config = wallet.joinmarket
        role_str = joinmarket_config.role.value if joinmarket_config and joinmarket_config.role else "maker"

        client = JoinMarketClientServer(name=name, port=port, type=role_str, delay=delay, stop=stop)


        start = time()
        if not client.wait_wallet(timeout=60):
            print(
                f"- could not start {name} (application timeout {time() - start} seconds)"
            )
            return None

        print(f"- started {client.name} (wait took {time() - start} seconds)")
        return client

    def stop_client(self, idx: int):
        name = f"jcs-{idx:03}"
        self.driver.stop(name)

    def store_engine_logs(self, data_path):
        # TODO: store irc logs.
        pass

    def update_coinjoins_joinmarket(self):
        for client in self.clients:
            state = client.get_status()
            # print(state)
            if client.type == "maker" and not client.maker_running and not client.delay[0] > self.current_block:
                client.start_maker(0, 5000, 0.00004, "sw0reloffer", 30000)
                print(f"Starting maker {client.name}")

            if client.type == "taker" and not client.coinjoin_in_process and not client.delay[0] > self.current_block:
                self.current_round += 1
                address = client.get_new_address()
                client.start_coinjoin(0, 40000, 4, address)
                client.coinjoin_start = self.current_block
                print(f"Starting coinjoin {client.name}")

            if client.type == "taker" and client.coinjoin_in_process and client.coinjoin_start + 4 < self.current_block:
                self.current_round -= 1
                client.stop_coinjoin()
                client.coinjoin_in_process = False
                print(f"Stopping coinjoin {client.name}")


    def run_engine(self):
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
            
        self.update_invoice_payments()
        initial_block = self.node.get_block_count()
        for i in range(5):
            # Takers need 3 confirmations of transactions for the sourcing commitments
            self.node.mine_block()

        while (self.scenario.rounds == 0 or self.current_round < self.scenario.rounds) and (
                self.scenario.blocks == 0 or self.current_block < self.scenario.blocks):
            for _ in range(3):
                try:
                    self.current_block = self.node.get_block_count() - initial_block  # type: ignore
                    break
                except Exception as e:
                    print(f"- could not get blocks".ljust(60), end="\r")
                    print(f"Block exception: {e}", file=sys.stderr)

            self.update_invoice_payments()
            self.update_coinjoins_joinmarket()

            print(
                f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60),
                end="\r",
            )
            sleep(1)

        print()
        print(f"- limit reached")
        sleep(60)
        self.node.mine_block()
