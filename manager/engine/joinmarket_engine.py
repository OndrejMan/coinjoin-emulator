from manager.engine.engine_base import EngineBase
from manager.engine.configuration import ScenarioConfig, WalletConfig, JoinMarketConfig, JoinMarketRole
from manager.wasabi_clients.joinmarket_client import JoinMarketClientServer
from time import sleep, time
import sys
import json
import os

class JoinmarketEngine(EngineBase):

    def __init__(self, args, driver):
        super().__init__(args, driver, "/home/joinmarket")
        self.joinmarket_round_events = []

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
                f"{self.args.image_prefix}joinmarket-client-server",
                env={},  # Add any necessary environment variables
                ports={28183: port},
                cpu=1.0,
                memory=2048,
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise Exception("Could not start distributor")

        self.distributor = self.init_joinmarket_clientserver(
            name=name,
            host=ip if self.args.proxy else self.args.control_ip,
            port=28183 if self.args.proxy else manager_ports[28183],
            proxy=self.args.proxy,
        )

        start = time()
        if not self.distributor.wait_wallet(timeout=60):
            print(f"- could not start {name} (application timeout)")
            raise Exception("Could not start distributor")
        print(f"- started distributor")


    def init_joinmarket_clientserver(
        self,
        name,
        port,
        host="localhost",
        type="maker",
        delay=(0, 0),
        stop=(0, 0),
        proxy="",
    ):
        return JoinMarketClientServer(
            name=name,
            host=host,
            port=port,
            type=type,
            delay=delay,
            stop=stop,
            proxy=proxy,
        )


    def start_client(self, idx: int, wallet: WalletConfig):
        name = f"jcs-{idx:03}"
        port = 28184 + idx
        try:
            ip, manager_ports = self.driver.run(
                name,
                f"{self.args.image_prefix}joinmarket-client-server",
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

        client = self.init_joinmarket_clientserver(
            name=name,
            host=ip if self.args.proxy else self.args.control_ip,
            port=28183 if self.args.proxy else manager_ports[28183],
            type=role_str,
            delay=delay,
            stop=stop,
            proxy=self.args.proxy,
        )


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

    def validate_clients(self):
        takers = [client for client in self.clients if client.type == "taker"]
        makers = [client for client in self.clients if client.type == "maker"]
        if not takers:
            raise RuntimeError("JoinMarket scenario requires at least one started taker client")
        if not makers:
            raise RuntimeError("JoinMarket scenario requires at least one started maker client")

    def store_engine_logs(self, data_path):
        labels = self.match_joinmarket_rounds_to_blocks(data_path)
        with open(os.path.join(data_path, "joinmarket_round_events.json"), "w") as f:
            json.dump(labels, f, indent=2)
            print("- stored JoinMarket round labels")

    def match_joinmarket_rounds_to_blocks(self, data_path):
        labels_by_destination = {
            event["destination_address"]: dict(event)
            for event in self.joinmarket_round_events
            if event.get("destination_address")
        }
        if not labels_by_destination:
            return []

        node_path = os.path.join(data_path, "btc-node")
        if not os.path.isdir(node_path):
            return list(labels_by_destination.values())

        for filename in sorted(os.listdir(node_path)):
            if not filename.startswith("block_") or not filename.endswith(".json"):
                continue
            with open(os.path.join(node_path, filename), "r") as f:
                block = json.load(f)
            block_height = block.get("height")
            for tx in block.get("tx", []):
                txid = tx.get("txid")
                for output in tx.get("vout", []):
                    script_pub_key = output.get("scriptPubKey") or {}
                    addresses = []
                    if script_pub_key.get("address"):
                        addresses.append(script_pub_key["address"])
                    addresses.extend(script_pub_key.get("addresses") or [])
                    for address in addresses:
                        event = labels_by_destination.get(address)
                        if event is not None and txid:
                            event["txid"] = txid
                            event["block_height"] = block_height
                            event["match_source"] = "destination_output"

        return sorted(
            labels_by_destination.values(),
            key=lambda event: (event.get("round_id", 0), event.get("taker", "")),
        )

    def update_coinjoins_joinmarket(self):
        total_started_rounds = len([
            event for event in self.joinmarket_round_events
            if event.get("status") in ("started", "stopped")
        ])
        for client in self.clients:
            state = client.get_status()
            # print(state)
            if client.type == "maker" and not client.maker_running and not client.delay[0] > self.current_block:
                client.start_maker(0, 5000, 0.00004, "sw0reloffer", 30000)
                print(f"Starting maker {client.name}")

            can_start_more_rounds = self.scenario.rounds == 0 or total_started_rounds < self.scenario.rounds
            if client.type == "taker" and not client.coinjoin_in_process and not client.delay[0] > self.current_block and can_start_more_rounds:
                address = client.get_new_address()
                maker_names = [
                    maker.name
                    for maker in self.clients
                    if maker.type == "maker" and maker.maker_running
                ]
                client.start_coinjoin(0, 40000, 4, address)
                client.coinjoin_start = self.current_block
                total_started_rounds += 1
                self.joinmarket_round_events.append({
                    "round_id": total_started_rounds,
                    "engine": "joinmarket",
                    "status": "started",
                    "taker": client.name,
                    "candidate_makers": maker_names,
                    "counterparties": 4,
                    "amount_sats": 40000,
                    "mixdepth": 0,
                    "destination_address": address,
                    "start_block": self.current_block,
                })
                print(f"Starting coinjoin {client.name}")

            if client.type == "taker" and client.coinjoin_in_process and client.coinjoin_start + 4 < self.current_block:
                client.stop_coinjoin()
                client.coinjoin_in_process = False
                self.current_round += 1
                for event in reversed(self.joinmarket_round_events):
                    if event.get("taker") == client.name and event.get("status") == "started":
                        event["status"] = "stopped"
                        event["stop_block"] = self.current_block
                        break
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
