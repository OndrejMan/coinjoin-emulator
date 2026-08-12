import math
import multiprocessing
import multiprocessing.pool
import random
import time
from time import sleep

from manager import utils
from manager.btc_node import BtcNode
from manager.driver import Driver
from manager.engine.base.logs import EngineLogsMixin
from manager.engine.base.protocols import EmulatorClient, EngineArgs, InvoiceDistributor
from manager.engine.configuration import FundConfig, ScenarioConfig, WalletConfig

DISTRIBUTOR_UTXOS = 200
BATCH_SIZE = 5  # smaller batches avoid UTXO race conditions
BTC = 100_000_000


def _has_fidelity_bond(wallet: WalletConfig) -> bool:
    """True when the wallet asks for a fidelity bond (typed scenario model)."""
    bond = (wallet.joinmarket.fidelity_bond if wallet.joinmarket else None) or {}
    return bool(bond.get("enabled", False))


class EngineBase(EngineLogsMixin):
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

        self.versions.add(self.scenario.default_version)
        if self.scenario.distributor_version is not None:
            self.versions.add(self.scenario.distributor_version)
        for wallet in self.scenario.wallets:
            if wallet.version is not None:
                self.versions.add(wallet.version)

    def prepare_images(self) -> None:
        raise NotImplementedError

    def prepare_image(self, name: str, path: str | None = None) -> None:
        prefixed_name = self.args.image_prefix + name
        if self.driver.has_image(prefixed_name):
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
        btc_node_ip, btc_node_ports, _ = self.driver.run(
            "btc-node",
            f"{self.args.image_prefix}btc-node",
            ports={18443: 18443, 18444: 18444},
            cpu=2.0,
            memory=2048,
            service_account="btc-node",
        )

        print(btc_node_ip, btc_node_ports)
        self.node = BtcNode(
            host=btc_node_ip if self.args.proxy or self.args.in_cluster else self.args.control_ip,
            port=18443 if self.args.proxy else btc_node_ports[18443],
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

    def init_client(self) -> object:
        raise NotImplementedError

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> EmulatorClient | None:
        raise NotImplementedError

    def stop_client(self, idx: int) -> None:
        raise NotImplementedError

    def _start_classified_wallets(
        self,
        pool: multiprocessing.pool.ThreadPool,
        wallet_list: list[tuple[int, WalletConfig]],
        fb_batch_size: int = 5,
        fb_batch_delay: int = 15,
    ) -> dict[int, EmulatorClient | None]:
        """
        Start a list of (idx, wallet) tuples with smart batching:
        - Regular wallets: all in parallel
        - FB wallets: in small batches to avoid Bitcoin RPC overload

        Returns dict: {idx: client} (client is None if startup failed)
        """
        # Classify into regular and FB wallets
        regular_wallets = []
        fb_wallets = []

        for idx, wallet in wallet_list:
            if _has_fidelity_bond(wallet):
                fb_wallets.append((idx, wallet))
            else:
                regular_wallets.append((idx, wallet))

        results: dict[int, EmulatorClient | None] = {}

        # Start regular wallets in parallel (fast)
        if regular_wallets:
            regular_clients = pool.starmap(self.start_client, regular_wallets)
            for (idx, _), client in zip(regular_wallets, regular_clients):
                results[idx] = client

        # Start FB wallets in batches (slow, avoid RPC overload)
        if fb_wallets:
            for batch_start in range(0, len(fb_wallets), fb_batch_size):
                batch_end = min(batch_start + fb_batch_size, len(fb_wallets))
                batch = fb_wallets[batch_start:batch_end]

                batch_clients = pool.starmap(self.start_client, batch)
                for (idx, _), client in zip(batch, batch_clients):
                    results[idx] = client

                # Wait before next batch (unless last batch)
                if batch_end < len(fb_wallets) and fb_batch_delay > 0:
                    print(f"  - waiting {fb_batch_delay}s before next batch")
                    sleep(fb_batch_delay)

        return results

    def start_clients(self, wallets: list[WalletConfig]) -> None:
        print("Starting clients")

        fb_batch_size = 5   # FB wallets per batch
        fb_batch_delay = 15  # Seconds between FB batches

        # Build initial wallet list with indices
        wallet_list = [(idx, wallet) for idx, wallet in enumerate(wallets, start=len(self.clients))]

        # Count wallet types for logging
        fb_count = sum(1 for _, w in wallet_list if _has_fidelity_bond(w))
        print(f"- {len(wallet_list) - fb_count} regular wallets, {fb_count} fidelity bond wallets")

        with multiprocessing.pool.ThreadPool() as pool:
            new_clients: list[EmulatorClient | None] = [None] * len(wallets)

            # Initial startup
            print(f"- starting {len(wallet_list)} wallets")
            if fb_count > 0:
                print(f"  - FB wallets will be started in batches of {fb_batch_size}")

            startup_results = self._start_classified_wallets(pool, wallet_list, fb_batch_size, fb_batch_delay)
            for idx, client in startup_results.items():
                new_clients[idx - len(self.clients)] = client

            # Retry logic (uses same classification/batching)
            for retry_attempt in range(3):
                failed_indices = [
                    idx for idx, client in enumerate(new_clients, start=len(self.clients))
                    if client is None
                ]

                if not failed_indices:
                    break

                print(f"- failed to start {len(failed_indices)} clients; retrying ...")

                # Stop and rebuild wallet list for failed clients
                for idx in failed_indices:
                    self.stop_client(idx)
                sleep(60)

                retry_wallet_list = [(idx, wallets[idx - len(self.clients)]) for idx in failed_indices]

                # Retry with same smart batching
                retry_results = self._start_classified_wallets(pool, retry_wallet_list, fb_batch_size, fb_batch_delay)
                for idx, client in retry_results.items():
                    new_clients[idx - len(self.clients)] = client
            else:
                # After 3 retries, filter out None values
                started = [client for client in new_clients if client is not None]
                print(f"- failed to start {len(wallets) - len(started)} clients; continuing ...")
                new_clients = list(started)

        self.clients.extend(client for client in new_clients if client is not None)

    def fund_distributor(self, btc_amount: int | float) -> None:
        print("Funding distributor")
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        if self.distributor is None:
            raise RuntimeError("Distributor is not initialized")

        # Round each UTXO up to a whole satoshi so the total meets the target
        # even when the amount does not divide evenly. Integer-dividing by BTC
        # here would fund every address with 0 BTC for any total below 200 BTC.
        per_utxo_sats = math.ceil(btc_amount * BTC / DISTRIBUTOR_UTXOS)
        for _ in range(DISTRIBUTOR_UTXOS):
            self.node.fund_address(
                self.distributor.get_new_address(),
                # Bitcoin Core rejects scientific notation, so keep 8 decimals.
                float(f"{per_utxo_sats / BTC:.8f}"),
            )

        while (balance := self.distributor.get_balance()) < btc_amount * BTC:
            sleep(1)
        print(f"- funded (current balance {balance / BTC:.8f} BTC)")






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

    def update_invoice_payments(self) -> None:
        due = list(filter(lambda x: x[0] <= self.current_block and x[1] <= self.current_round, self.invoices.keys()))
        for i in due:
            self.pay_invoices(self.invoices.pop(i, []))

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
                    raise TypeError(f"unsupported fund entry for {client.name}: {fund!r}")
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
        try:
            for batch in utils.batched(addressed_invoices, BATCH_SIZE):
                for _ in range(3):
                    try:
                        if self.distributor is None:
                            raise RuntimeError("Distributor is not initialized")
                        result = self.distributor.send(batch)
                        if str(result) == "timeout":
                            print("- transaction timeout")
                            continue
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

        except Exception as e:
            print("- invoice payment failed")
            raise e

    def prepare_additional_funding(self, wallets: list[WalletConfig]) -> None:
        """
        Hook for engines to perform additional post-funding setup.
        Default implementation does nothing.

        Args:
            wallets: List of wallet configurations
        """
        pass
    
    def run(self) -> None:
        print(f"=== Scenario {self.scenario.name} ===")
        if not getattr(self.args, "no_logs", False):
            self.ensure_log_run_path_available()
        self.prepare_images()
        self.start_infrastructure()
        self.fund_distributor(5000)
        self.start_clients(self.scenario.wallets)
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
