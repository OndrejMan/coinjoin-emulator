from ..btc_node import BtcNode
from ..utils import batched
from .configuration import ScenarioConfig, WalletConfig, FundConfig
from time import sleep
from typing import Protocol
import random
import os
import json
import multiprocessing
import multiprocessing.pool
import math
import shutil
import datetime

DISTRIBUTOR_UTXOS = 10
BATCH_SIZE = 20
BTC = 100_000_000


class EngineArgs(Protocol):
    command: str
    scenario: str | None
    image_prefix: str
    force_rebuild: bool
    btcFolder: str | None
    proxy: str
    control_ip: str
    btc_node_ip: str
    wasabi_backend_ip: str


class DriverProtocol(Protocol):
    def has_image(self, name: str) -> bool: ...
    def build(self, name: str, path: str) -> object: ...
    def pull(self, name: str) -> object: ...
    def run(
        self,
        name: str,
        image: str,
        env: dict[str, str | None] | None = None,
        ports: dict[int, int] | None = None,
        skip_ip: bool = False,
        cpu: float = 0.1,
        memory: int = 768,
        volumes: dict[str, dict[str, str]] | None = None,
    ) -> tuple[str, dict[int, int]]: ...
    def stop(self, name: str) -> object: ...
    def download(self, name: str, src_path: str, dst_path: str) -> object: ...
    def peek(self, name: str, path: str) -> str: ...
    def logs(self, name: str) -> str: ...
    def upload(self, name: str, src_path: str, dst_path: str) -> object: ...
    def cleanup(self, image_prefix: str = "") -> object: ...


class EmulatorClient(Protocol):
    name: str
    type: str
    maker_running: bool
    coinjoin_in_process: bool
    coinjoin_start: int
    delay: tuple[int, int]
    stop: tuple[int, int]

    def get_new_address(self) -> str: ...
    def get_status(self) -> object: ...
    def get_balance(self) -> int: ...
    def start_maker(
        self,
        txfee: int,
        cjfee_a: int,
        cjfee_r: float,
        ordertype: str,
        minsize: int,
    ) -> object: ...
    def start_coinjoin(
        self,
        mixdepth: int,
        amount_sats: int,
        counterparties: int,
        destination: str,
    ) -> object: ...
    def list_coins(self) -> object: ...
    def list_unspent_coins(self) -> object: ...
    def list_keys(self) -> object: ...
    def stop_coinjoin(self) -> object: ...


class InvoiceDistributor(Protocol):
    def get_new_address(self) -> str: ...
    def get_balance(self) -> int: ...
    def wait_wallet(self, timeout: int | None = None) -> bool: ...
    def send(self, invoices: list[tuple[str, int]]) -> object: ...


class EngineBase:
    def __init__(self, args: EngineArgs, driver: DriverProtocol, log_src_path: str) -> None:
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

        self.versions.add(self.scenario.default_version)
        if self.scenario.distributor_version is not None:
            self.versions.add(self.scenario.distributor_version)
        for wallet in self.scenario.wallets:
            if wallet.version is not None:
                self.versions.add(wallet.version)

    def prepare_images(self) -> None:
        raise NotImplementedError

    def prepare_image(self, name: str, path: str | None = None, local_build: bool = False) -> None:
        prefixed_name = self.args.image_prefix + name
        if local_build:
            self.driver.build(prefixed_name, f"./containers/{name}" if path is None else path)
            print(f"- image built {prefixed_name}")
        elif self.driver.has_image(prefixed_name):
            if self.args.force_rebuild:
                if self.args.image_prefix:
                    self.driver.pull(prefixed_name)
                    print(f"- image pulled {prefixed_name}")
                else:
                    self.driver.build(name, f"./containers/{name}" if path is None else path)
                    print(f"- image rebuilt {prefixed_name}")
            else:
                print(f"- image reused {prefixed_name}")
        elif self.args.image_prefix:
            self.driver.pull(prefixed_name)
            print(f"- image pulled {prefixed_name}")
        else:
            self.driver.build(name, f"./containers/{name}" if path is None else path)
            print(f"- image built {prefixed_name}")

    def start_infrastructure(self) -> None:
        print("Starting infrastructure")
        self.start_btc_node()
        self.start_engine_infrastructure()
        self.start_distributor()

    def start_btc_node(self) -> None:
        node_volumes = None
        if self.args.btcFolder:
            absolute_host_path = os.path.abspath(self.args.btcFolder)
            print(f"- mounting external btc-data from: {absolute_host_path}")
            node_volumes = {
                absolute_host_path: {
                    'bind': '/home/bitcoin/data', 
                    'mode': 'rw'
                }
            }
        else:
            print("- no btcFolder provided; using internal container storage")

        print("- starting btc-node")
        btc_node_ip, btc_node_ports = self.driver.run(
            "btc-node",
            f"{self.args.image_prefix}btc-node",
            ports={18443: 18443, 18444: 18444},
            cpu=4.0,
            memory=8192,
            volumes=node_volumes
        )

        print("- middle btc-node")
        self.node = BtcNode(
            host=btc_node_ip if self.args.proxy else self.args.control_ip,
            port=18443 if self.args.proxy else btc_node_ports[18443],
            internal_ip=btc_node_ip,
            proxy=self.args.proxy,
        )
        print("- waiting btc-node")
        self.node.wait_ready()
        print("- started btc-node")

    def start_engine_infrastructure(self) -> None:
        raise NotImplementedError

    def start_distributor(self) -> None:
        raise NotImplementedError

    def init_client(self) -> object:
        raise NotImplementedError

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> EmulatorClient | None:
        raise NotImplementedError

    def stop_client(self, idx: int) -> None:
        raise NotImplementedError

    def start_clients(self, wallets: list[WalletConfig]) -> None:
        print("Starting clients")
        with multiprocessing.pool.ThreadPool() as pool:
            new_clients = pool.starmap(self.start_client, enumerate(wallets, start=len(self.clients)))

            for _ in range(3):
                restart_idx = list(
                    map(
                        lambda x: x[0],
                        filter(
                            lambda x: x[1] is None,
                            enumerate(new_clients, start=len(self.clients)),
                        ),
                    )
                )

                if not restart_idx:
                    break
                print(f"- failed to start {len(restart_idx)} clients; retrying ...")
                for idx in restart_idx:
                    self.stop_client(idx)
                sleep(60)
                restarted_clients = pool.starmap(
                    self.start_client,
                    ((idx, wallets[idx - len(self.clients)]) for idx in restart_idx),
                )
                for idx, client in enumerate(restarted_clients):
                    if client is not None:
                        new_clients[restart_idx[idx]] = client
            else:
                new_clients = [client for client in new_clients if client is not None]
                print(f"- failed to start {len(wallets) - len(new_clients)} clients; continuing ...")
        self.clients.extend(client for client in new_clients if client is not None)

        if len(new_clients) == 0 and len(wallets) > 0:
            raise RuntimeError("No emulator clients started successfully")

    def validate_clients(self) -> None:
        pass

    def fund_distributor(self, btc_amount: int | float) -> None:
        print("Funding distributor")
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        if self.distributor is None:
            raise RuntimeError("Distributor is not initialized")

        for _ in range(DISTRIBUTOR_UTXOS):
            self.node.fund_address(
                self.distributor.get_new_address(),
                math.ceil(btc_amount * BTC / DISTRIBUTOR_UTXOS) // BTC,
            )

        while (balance := self.distributor.get_balance()) < btc_amount * BTC:
            sleep(1)
        print(f"- funded (current balance {balance / BTC:.8f} BTC)")

    def store_client_logs(self, client: EmulatorClient, data_path: str) -> None:
        sleep(random.random() * 3)
        client_path = os.path.join(data_path, client.name)
        os.mkdir(client_path)
        with open(os.path.join(client_path, "coins.json"), "w", encoding="utf-8") as f:
            json.dump(client.list_coins(), f, indent=2)
            print(f"- stored {client.name} coins")
        with open(
            os.path.join(client_path, "unspent_coins.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(client.list_unspent_coins(), f, indent=2)
            print(f"- stored {client.name} unspent coins")
        with open(os.path.join(client_path, "keys.json"), "w", encoding="utf-8") as f:
            json.dump(client.list_keys(), f, indent=2)
            print(f"- stored {client.name} keys")
        try:
            self.driver.download(client.name, self.log_src_path, client_path)

            print(f"- stored {client.name} logs")
        except:
            print(f"- could not store {client.name} logs")

    def store_logs(self) -> None:
        print("Storing logs")
        time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        experiment_path = f"./logs/{time}_{self.scenario.name}"
        data_path = os.path.join(experiment_path, "data")
        os.makedirs(data_path)

        with open(
            os.path.join(experiment_path, "scenario.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(self.scenario.to_dict(), f, indent=2)
            print("- stored scenario")

        stored_blocks = 0
        node_path = os.path.join(data_path, "btc-node")
        os.mkdir(node_path)
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        while stored_blocks < self.node.get_block_count():
            block_hash = self.node.get_block_hash(stored_blocks)
            block = self.node.get_block_info(block_hash)
            with open(
                os.path.join(node_path, f"block_{stored_blocks}.json"),
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(block, f, indent=2)
            stored_blocks += 1
        print(f"- stored {stored_blocks} blocks")

        self.store_engine_logs(data_path)

        # TODO parallelize (driver cannot be simply passed to new threads)
        for client in self.clients:
            self.store_client_logs(client, data_path)

        shutil.make_archive(experiment_path, "zip", *os.path.split(experiment_path))
        print("- zip archive created")

    def store_engine_logs(self, data_path: str) -> None:
        raise NotImplementedError

    def stop_coinjoins(self) -> None:
        print("Stopping coinjoins")
        for client in self.clients:
            client.stop_coinjoin()
            print(f"- stopped mixing {client.name}")

    def update_invoice_payments(self) -> None:
        due = list(filter(lambda x: x[0] <= self.current_block and x[1] <= self.current_round, self.invoices.keys()))
        for i in due:
            self.pay_invoices(self.invoices.get(i, []))
            self.invoices.pop(i, None)
            print(f"- paid invoices for block {i[0]} and round {i[1]}")
        print(f"- {len(self.invoices)} invoices still pending")

    def prepare_invoices(self, wallets: list[WalletConfig]) -> None:
        print("Preparing invoices")
        client_invoices = [(client, wallet.funds) for client, wallet in zip(self.clients, wallets)]

        for client, funds in client_invoices:
            for fund in funds:
                block = 0
                round = 0
                if isinstance(fund, int):
                    value = fund
                elif isinstance(fund, FundConfig):
                    value = fund.value
                    block = fund.delay_blocks or 0
                    round = fund.delay_rounds or 0
                else:
                    raise TypeError(f"Unexpected fund config: {fund!r}")
                addressed_invoice = (client.get_new_address(), value)
                if (block, round) not in self.invoices:
                    self.invoices[(block, round)] = [addressed_invoice]
                else:
                    self.invoices[(block, round)].append(addressed_invoice)

        for addressed_invoices in self.invoices.values():
            random.shuffle(addressed_invoices)

        print(f"- prepared {sum(map(len, self.invoices.values()))} invoices")

    def pay_invoices(self, addressed_invoices: list[tuple[str, int]]) -> None:
        print(
            f"- paying {len(addressed_invoices)} invoices (batch size {BATCH_SIZE}, block {self.current_block}, round {self.current_round})"
        )
        for batch in batched(addressed_invoices, BATCH_SIZE):
            for _ in range(3):
                try:
                    if self.distributor is None:
                        raise RuntimeError("Distributor is not initialized")
                    result = self.distributor.send(list(batch))
                    if str(result) == "timeout" or result is False or result is None:
                        print("- transaction timeout")
                        continue
                    print(f"- transaction sent with txid {result}")
                    break
                except Exception as e:
                    # https://github.com/zkSNACKs/WalletWasabi/issues/12764
                    if "Bad Request" in str(e):
                        print("- transaction error (bad request)")
                    else:
                        print(f"- transaction error ({e})")
            else:
                print("- invoice payment failed")
                raise Exception("Invoice payment failed")
            print(f"- paid batch of {len(batch)} invoices")

    def run(self) -> None:
        print(f"=== Scenario {self.scenario.name} ===")
        self.prepare_images()
        self.start_infrastructure()
        self.fund_distributor(500)
        self.start_clients(self.scenario.wallets)
        self.validate_clients()
        self.prepare_invoices(self.scenario.wallets)
        print("Running simulation")
        self.run_engine()

    def run_engine(self) -> None:
        raise NotImplementedError
