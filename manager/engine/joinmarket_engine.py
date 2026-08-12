import asyncio
import json
import os
import shutil
import sys
from collections.abc import Iterator
from time import sleep, time
from typing import cast

from manager.engine.base.manifest import ProducerLabelEvidence
from manager.driver import Driver
from manager.engine.configuration import JoinMarketConfig, JoinMarketRole, ScenarioConfig, WalletConfig
from manager.engine.engine_base import EngineArgs, EngineBase
from manager.engine.joinmarket.events import (
    collect_round_events,
    match_round_events_to_blocks,
    producer_label_evidence,
)
from manager.engine.joinmarket.lifecycle import JoinMarketLifecycleMixin
from manager.engine.joinmarket.round_event_record import RoundEvent
from manager.engine.joinmarket.rounds import JoinMarketRoundsMixin
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer
from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient


class JoinmarketEngine(JoinMarketRoundsMixin, JoinMarketLifecycleMixin, EngineBase):

    def __init__(self, args: EngineArgs, driver: Driver) -> None:
        super().__init__(args, driver,
                         log_src_path="/home/joinmarket/.joinmarket/logs")
        self.obwatch_client: OrderbookWatchClient | None = None
        # Feature flag to enable async client updates (default: enabled for better performance)
        self.async_updates = bool(getattr(args, "async_updates", True))
        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_resource_check = 0  # Track when we last checked resources

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



    def start_engine_infrastructure(self) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        self.node.create_wallet("jm_wallet")
        print("- created jm_wallet in BitcoinCore")

        self.start_irc_server()
        print("- started irc-server")

        # Start the JoinMarket orderbook watcher service and attach a client to poll it
        try:
            self.start_orderbook_watch()
            print("- started orderbook watcher")
        except Exception as e:
            print(f"- could not start orderbook watcher ({e})")





    def prepare_additional_funding(self, wallets: list[WalletConfig]) -> None:
        """
        JoinMarket-specific additional funding setup.
        Creates and funds fidelity bonds for wallets that have bond configuration.
        """
        bond_clients = []
        bond_invoices = []

        print("Preparing fidelity bonds")

        for client, wallet in zip(self.clients, wallets):
            fidelity_bond_config = (wallet.joinmarket.fidelity_bond if wallet.joinmarket else None) or {}

            if not fidelity_bond_config.get("enabled", False):
                continue

            try:
                # Extract bond configuration
                amount = fidelity_bond_config.get("amount", 50000)  # Default 50k sats
                locktime = fidelity_bond_config.get("locktime")

                if not locktime:
                    print(f"Warning: No locktime specified for fidelity bond on {client.name}, skipping")
                    continue

                # Create the bond
                jm_client = cast(JoinMarketClientServer, client)
                bond_info = jm_client.create_fidelity_bond(
                    amount=int(cast(int, amount)),
                    locktime=str(locktime),
                    current_block=self.current_block
                )

                # Prepare funding invoice
                bond_address = str(bond_info["address"])
                bond_invoice = (bond_address, int(cast(int, amount)))
                bond_invoices.append(bond_invoice)
                bond_clients.append((client, bond_address))

                print(f"- prepared fidelity bond for {client.name}: {amount} sats to {bond_address}")

            except Exception as e:
                print(f"Error creating fidelity bond for {client.name}: {e}")
                raise Exception(f"Failed to create fidelity bond for {client.name}: {e}")

        if bond_invoices:
            print(f"Funding {len(bond_invoices)} fidelity bonds")

            try:
                # Fund all bonds in a single batch
                self.pay_invoices(bond_invoices)

                # Mark bonds as funded
                for bond_client, bond_address in bond_clients:
                    cast(JoinMarketClientServer, bond_client).mark_bond_funded(bond_address)

                print(f"- funded {len(bond_invoices)} fidelity bonds")

                # Mine additional blocks to ensure fidelity bond transactions are confirmed
                # JoinMarket needs confirmed UTXOs to calculate bond values for maker offers
                print("Mining blocks to confirm fidelity bond transactions")
                if self.node is None:
                    raise RuntimeError("Bitcoin node is not initialized")
                for _ in range(15):  # Mine 15 blocks for solid confirmation
                    self.node.mine_block()
                print("- fidelity bond confirmations completed")

            except Exception as e:
                print(f"Failed to fund fidelity bonds: {e}")
                raise Exception(f"Failed to fund fidelity bonds: {e}")
        else:
            print("- no fidelity bonds to fund")


    def collect_round_events(self) -> list[RoundEvent]:
        """Copy producer-owned round records from all clients."""
        return collect_round_events([
            cast(list[RoundEvent], getattr(client, "round_events", []))
            for client in self.clients
        ])

    def match_joinmarket_rounds_to_blocks(self, data_path: str) -> list[RoundEvent]:
        """Reconcile copied client records with blocks exported under data_path."""
        node_path = os.path.join(data_path, "btc-node")

        def exported_blocks() -> Iterator[dict[str, object]]:
            """Yield exported blocks one at a time to avoid retaining them all."""
            if not os.path.isdir(node_path):
                return
            for filename in sorted(os.listdir(node_path)):
                if filename.startswith("block_") and filename.endswith(".json"):
                    with open(os.path.join(node_path, filename), encoding="utf-8") as stream:
                        yield cast(dict[str, object], json.load(stream))

        return match_round_events_to_blocks(self.collect_round_events(), exported_blocks())

    def store_round_events(self, data_path: str) -> ProducerLabelEvidence:
        """Store reconciled labels and return their producer-label evidence."""
        labels = self.match_joinmarket_rounds_to_blocks(data_path)
        with open(os.path.join(data_path, "joinmarket_round_events.json"), "w", encoding="utf-8") as stream:
            json.dump(labels, stream, indent=2)
        print(f"- stored {len(labels)} JoinMarket round labels")
        return dict(producer_label_evidence(labels, []))

    def store_engine_logs(self, data_path: str) -> dict[str, object] | None:
        print("- storing engine-logs")
        self.store_orderbook_snapshots(data_path)
        return self.store_round_events(data_path)

    def store_orderbook_snapshots(self, data_path: str) -> None:
        # Store orderbook snapshots, grouped under data_path/orderbook/<client.name>
        print(f"- storing {data_path}")
        ob_root = os.path.join(data_path, "orderbook")
        os.makedirs(ob_root, exist_ok=True)
        client = self.obwatch_client

        # Check if orderbook watcher client exists
        if client is None:
            print("- no orderbook watcher client to store")
            return

        src = getattr(client, "snapshot_dir", None)
        if not src or not os.path.isdir(src):
            print(f"- no snapshots to store for {client.name}")
            return
        dst = os.path.join(ob_root, client.name)
        os.makedirs(dst, exist_ok=True)
        try:
            # Prefer copytree with dirs_exist_ok when possible to preserve structure
            # Copy content of src into dst (merge)
            for root, dirs, files in os.walk(src):
                print(f"- found {root}")
                rel = os.path.relpath(root, src)
                target_dir = os.path.join(dst, rel) if rel != "." else dst
                os.makedirs(target_dir, exist_ok=True)
                for f in files:
                    print(f"- found {f}")
                    shutil.copy2(os.path.join(root, f), os.path.join(target_dir, f))
            print(f"- stored orderbook snapshots for {client.name}")
        except Exception as e:
            print(f"- could not store orderbook snapshots for {client.name}: {e}")










    async def cleanup_async_clients(self) -> None:
        """
        Cleanup async HTTP clients to prevent resource leaks.
        Should be called when shutting down the engine.
        """
        cleanup_tasks = []
        
        for client in self.clients:
            if hasattr(client, 'aclose'):
                cleanup_tasks.append(client.aclose())
        
        if self.obwatch_client and hasattr(self.obwatch_client, 'aclose'):
            cleanup_tasks.append(self.obwatch_client.aclose())
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            print("- closed all async HTTP clients")


    def shutdown_engine(self) -> None:
        """
        Shutdown the engine and cleanup resources.
        """
        if self.async_updates:
            try:
                asyncio.run(self.cleanup_async_clients())
            except Exception as e:
                print(f"- error during async client cleanup: {e}")

    def run_engine(self) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")

        # Note: Initial invoice payments now happen before this method is called
        try:
            initial_block = self.node.get_block_count()
        except Exception as e:
            print(f"- could not get initial block count: {e}")
            initial_block = 0
        for i in range(5):
            # Takers need 3 confirmations of transactions for the sourcing commitments
            self.node.mine_block()

        print(f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60))

        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            while (self.scenario.rounds == 0 or self.current_round < self.scenario.rounds ) and (
                    self.scenario.blocks == 0 or self.current_block < self.scenario.blocks):
                # refresh block count
                for _ in range(3):
                    try:
                        self.current_block = self.node.get_block_count() - initial_block
                        break
                    except Exception as e:
                        print("- could not get blocks".ljust(60), end="\r")
                        print(f"Block exception: {e}", file=sys.stderr)

                # Check resource usage every 5 minutes (10 iterations * 30s = 5 min)
                current_time = int(time())
                if current_time - self.last_resource_check > 300:  # 5 minutes
                    try:
                        self.check_client_resources()
                        self.last_resource_check = current_time
                    except Exception as e:
                        print(f"- resource check failed: {e}")

                # safe updates
                try:
                    self.update_invoice_payments()
                except Exception as e:
                    print(f"- invoice update failed: {e}")
                try:
                    if self.async_updates:
                        # Use async path for parallel client updates
                        self.loop.run_until_complete(self.update_coinjoins_joinmarket_async())
                    else:
                        # Use synchronous path (legacy)
                        self.update_coinjoins_joinmarket()
                except Exception as e:
                    print(f"- coinjoin update failed: {e}")
                print(
                    f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60),
                    end="\r",
                )
                sleep(30)

            print()
            print("- limit reached")
            sleep(60)
            self.node.mine_block()

        finally:
            if self.loop is not None and not self.loop.is_closed():
                self.loop.close()
