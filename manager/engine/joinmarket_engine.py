import backoff
import asyncio

from manager.engine.engine_base import EngineBase
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer
from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient
from time import sleep, time
import os
import shutil
SCENARIO = {
    "name": "default",
    "default_version": "joinmarket",
    "rounds": 0,  # the number of coinjoins after which the simulation stops (0 for no limit)
    "blocks": 0,  # the number of mined blocks after which the simulation stops (0 for no limit)
    "wallets": [],
}
import sys



class JoinmarketEngine(EngineBase):

    def __init__(self, args, driver):
        super().__init__(args, driver,
                         log_src_path="/home/joinmarket/.joinmarket/logs")
        self.obwatch_client = None
        # Feature flag to enable async client updates (default: enabled for better performance)
        self.async_updates = getattr(args, 'async_updates', True)

    def default_scenario(self):
        return SCENARIO

    def prepare_images(self):
        print("Preparing images")
        self.prepare_image("btc-node")
        self.prepare_image("joinmarket-client-server")
        self.prepare_image("irc-server")


    def start_engine_infrastructure(self):
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

    def start_orderbook_watch(self):
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

    def store_engine_logs(self, data_path):
        # Store orderbook snapshots, grouped under data_path/orderbook/<client.name>
        print("- storing engine-logs")
        print(f"- storing {data_path}")
        ob_root = os.path.join(data_path, "orderbook")
        os.makedirs(ob_root, exist_ok=True)
        client = self.obwatch_client
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


    @staticmethod
    def init_joinmarket_clientserver(name, port, host="localhost", proxy=None):
        print(f"Starting joinmarket-client-server: {name}")
        client = JoinMarketClientServer(name=name, port=port, host=host, proxy=proxy)

        ensure_client_session(client, name)

        if not client.wait_wallet(timeout=30000):
            print(f"- could not start {name} (application timeout)")
            raise Exception("Could not start distributor")
        return client


    def start_client(self, idx: int, wallet=None):
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

    def update_coinjoins_joinmarket(self):
        for client in self.clients:
            try:
                delta = client.update(self.current_block, self.current_round)
                # Apply any change in round count; alternatively, have the client trigger an event.
                self.current_round += delta
            except Exception as e:
                print(f"- could not update {client.name} ({e})")

        try:
            self.obwatch_client.update(self.current_block, self.current_round)
        except Exception as e:
            print(f"- could not update obwatch client ({e})")

    async def update_coinjoins_joinmarket_async(self):
        """
        Async version: Update all clients in parallel using asyncio.gather()
        """
        # Create tasks for all client updates
        client_tasks = []
        for client in self.clients:
            task = self._update_client_async(client)
            client_tasks.append(task)
        
        # Add orderbook watcher client task if it exists
        if self.obwatch_client:
            obwatch_task = self._update_obwatch_async(self.obwatch_client)
            client_tasks.append(obwatch_task)
        
        # Run all updates concurrently
        results = await asyncio.gather(*client_tasks, return_exceptions=True)
        
        # Process results and update round count
        for i, result in enumerate(results[:-1] if self.obwatch_client else results):
            if isinstance(result, Exception):
                client_name = self.clients[i].name if i < len(self.clients) else "unknown"
                print(f"- could not update {client_name} ({result})")
            else:
                # Apply any change in round count
                self.current_round += result

    async def _update_client_async(self, client):
        """Helper to update a single client asynchronously"""
        try:
            delta = await client.update_async(self.current_block, self.current_round)
            return delta
        except Exception as e:
            print(f"- could not update {client.name} ({e})")
            return 0

    async def _update_obwatch_async(self, obwatch_client):
        """Helper to update orderbook watcher client asynchronously"""
        try:
            return await obwatch_client.update_async(self.current_block, self.current_round)
        except Exception as e:
            print(f"- could not update obwatch client ({e})")
            return 0

    async def cleanup_async_clients(self):
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

    def shutdown_engine(self):
        """
        Shutdown the engine and cleanup resources.
        """
        if self.async_updates:
            try:
                asyncio.run(self.cleanup_async_clients())
            except Exception as e:
                print(f"- error during async client cleanup: {e}")

    def run_engine(self):
        try:
            # Use synchronous invoice payments (reliable, simple)
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

        while ( self.scenario["rounds"] == 0 or self.current_round < self.scenario["rounds"] ) and (
                self.scenario["blocks"] == 0 or self.current_block < self.scenario["blocks"]):
            # refresh block count
            for _ in range(3):
                try:
                    self.current_block = self.node.get_block_count() - initial_block
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
                if self.async_updates:
                    # Use async path for parallel client updates
                    asyncio.run(self.update_coinjoins_joinmarket_async())
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
        print(f"- limit reached")
        sleep(60)
        self.node.mine_block()

@backoff.on_exception(backoff.expo, Exception, max_tries=5)
def ensure_client_session(client, name):
    if not client.session():
        print(f"- could not start {name} (session timeout)")
        raise Exception("Could not start distributor")