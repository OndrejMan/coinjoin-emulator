from .engine_base import DriverProtocol, EmulatorClient, EngineArgs, EngineBase, BTC
from .configuration import ScenarioConfig, WalletConfig, JoinMarketConfig, JoinMarketRole
from ..wasabi_clients.joinmarket_client import JoinMarketClientServer
from time import sleep, time
import sys
import json
import os
import threading
from typing import cast

JOINMARKET_COINJOIN_AMOUNT_SATS = 40000
JOINMARKET_COUNTERPARTIES = 4
JOINMARKET_MAKER_MIN_SIZE_SATS = 30000
JOINMARKET_ROUND_TIMEOUT_BLOCKS = 180
JOINMARKET_FINAL_SETTLE_BLOCKS = 1
JOINMARKET_LOOP_SLEEP_SECONDS = 1
JOINMARKET_DISTRIBUTOR_RPC_WALLET = "jm_wallet_distributor"


class JoinmarketEngine(EngineBase):

    def __init__(self, args: EngineArgs, driver: DriverProtocol) -> None:
        super().__init__(args, driver, "/home/joinmarket")
        self.joinmarket_round_events: list[dict[str, object]] = []
        self._core_wallet_lock = threading.Lock()

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

    def prepare_images(self) -> None:
        print("Preparing images")
        self.prepare_image("btc-node")
        self.prepare_image("joinmarket-client-server", local_build=True)
        self.prepare_image("irc-server")


    def start_engine_infrastructure(self) -> None:
        self.start_irc_server()
        print("- started irc-server")

    def _core_wallet_name(self, client_name: str) -> str:
        return f"jm_wallet_{client_name.replace('-', '_')}"

    def _create_joinmarket_core_wallet(self, wallet_name: str) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")

        with self._core_wallet_lock:
            self.node.create_wallet(
                wallet_name,
                disable_private_keys=True,
            )
        print(f"- created {wallet_name} in BitcoinCore")


    def start_irc_server(self) -> None:
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


    def _dump_container_log(self, container_name: str, log_path: str) -> None:
        """Try to read a log file from a running container for diagnostics."""
        try:
            log_content = self.driver.logs(container_name)
            print(f"- {container_name} container logs:\n{log_content}")
        except Exception:
            print(f"- could not retrieve container logs from {container_name}")

        try:
            log_content = self.driver.peek(container_name, log_path)
            print(f"- {container_name} log ({log_path}):\n{log_content}")
        except Exception:
            print(f"- could not retrieve {log_path} from {container_name}")

    def start_distributor(self) -> None:
        name = "joinmarket-distributor"
        port = 28183  # Use a specific port for the distributor
        self._create_joinmarket_core_wallet(JOINMARKET_DISTRIBUTOR_RPC_WALLET)
        try:
            ip, manager_ports = self.driver.run(
                name,
                f"{self.args.image_prefix}joinmarket-client-server",
                env={"JM_RPC_WALLET_FILE": JOINMARKET_DISTRIBUTOR_RPC_WALLET},
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
        if not self.distributor.wait_wallet(timeout=180):
            elapsed = time() - start
            print(f"- could not start {name} (application timeout after {elapsed:.1f}s)")
            self._dump_container_log(name, "/home/joinmarket/jmwalletd.log")
            raise Exception("Could not start distributor")
        print(f"- started distributor (wait took {time() - start:.1f}s)")


    def init_joinmarket_clientserver(
        self,
        name: str,
        port: int,
        host: str = "localhost",
        type: str = "maker",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
        proxy: str = "",
    ) -> JoinMarketClientServer:
        return JoinMarketClientServer(
            name=name,
            host=host,
            port=port,
            type=type,
            delay=delay,
            stop=stop,
            proxy=proxy,
        )

    def init_client(self) -> object:
        raise NotImplementedError("JoinMarket clients require init_joinmarket_clientserver()")

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> JoinMarketClientServer | None:
        if wallet is None:
            raise ValueError("wallet configuration is required to start a JoinMarket client")

        name = f"jcs-{idx:03}"
        port = 28184 + idx
        core_wallet = self._core_wallet_name(name)
        self._create_joinmarket_core_wallet(core_wallet)
        try:
            ip, manager_ports = self.driver.run(
                name,
                f"{self.args.image_prefix}joinmarket-client-server",
                env={"JM_RPC_WALLET_FILE": core_wallet},
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
        if not client.wait_wallet(timeout=120):
            elapsed = time() - start
            print(
                f"- could not start {name} (application timeout {elapsed:.1f}s)"
            )
            self._dump_container_log(name, "/home/joinmarket/jmwalletd.log")
            return None

        print(f"- started {client.name} (wait took {time() - start} seconds)")
        return client

    def stop_client(self, idx: int) -> None:
        name = f"jcs-{idx:03}"
        self.driver.stop(name)

    def validate_clients(self) -> None:
        takers = [client for client in self.clients if client.type == "taker"]
        makers = [client for client in self.clients if client.type == "maker"]
        if not takers:
            raise RuntimeError("JoinMarket scenario requires at least one started taker client")
        if not makers:
            raise RuntimeError("JoinMarket scenario requires at least one started maker client")

    def store_engine_logs(self, data_path: str) -> None:
        labels = self.match_joinmarket_rounds_to_blocks(data_path)
        with open(os.path.join(data_path, "joinmarket_round_events.json"), "w") as f:
            json.dump(labels, f, indent=2)
            print("- stored JoinMarket round labels")

    def pay_invoices(self, addressed_invoices: list[tuple[str, int]]) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")

        print(
            f"- funding {len(addressed_invoices)} JoinMarket invoices directly "
            f"(block {self.current_block}, round {self.current_round})"
        )
        for address, amount_sats in addressed_invoices:
            self.node.fund_address(address, amount_sats / BTC)
            print(f"- funded {amount_sats} sats to {address}")

        if addressed_invoices:
            self.node.mine_block()
            print("- confirmed JoinMarket invoice funding")

    def match_joinmarket_rounds_to_blocks(self, data_path: str) -> list[dict[str, object]]:
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
                block = cast(dict[str, object], json.load(f))
            block_height = block.get("height")
            for tx in cast(list[dict[str, object]], block.get("tx", [])):
                txid = tx.get("txid")
                for output in cast(list[dict[str, object]], tx.get("vout", [])):
                    script_pub_key = cast(dict[str, object], output.get("scriptPubKey") or {})
                    addresses: list[object] = []
                    if script_pub_key.get("address"):
                        addresses.append(script_pub_key["address"])
                    addresses.extend(cast(list[object], script_pub_key.get("addresses") or []))
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

    def _script_addresses(self, output: dict[str, object]) -> list[object]:
        script_pub_key = cast(dict[str, object], output.get("scriptPubKey") or {})
        addresses: list[object] = []
        if script_pub_key.get("address"):
            addresses.append(script_pub_key["address"])
        addresses.extend(cast(list[object], script_pub_key.get("addresses") or []))
        return addresses

    def _find_round_event_tx(self, event: dict[str, object]) -> dict[str, object] | None:
        if event.get("txid"):
            return {
                "txid": event.get("txid"),
                "block_height": event.get("block_height"),
            }
        if self.node is None or not event.get("destination_address"):
            return None

        start_height = max(0, int(str(event.get("start_chain_height") or 0)))
        tip_height = self.node.get_block_count()
        for height in range(start_height, tip_height + 1):
            block_hash = self.node.get_block_hash(height)
            block = self.node.get_block_info(block_hash)
            for tx in cast(list[dict[str, object]], block.get("tx", [])):
                txid = tx.get("txid")
                for output in cast(list[dict[str, object]], tx.get("vout", [])):
                    if event["destination_address"] in self._script_addresses(output):
                        return {
                            "txid": txid,
                            "block_height": block.get("height", height),
                        }
        return None

    def _confirm_started_rounds(self) -> int:
        confirmed = 0
        for event in self.joinmarket_round_events:
            if event.get("status") != "started":
                continue

            match = self._find_round_event_tx(event)
            if not match:
                continue

            event["status"] = "confirmed"
            event["txid"] = match.get("txid")
            event["block_height"] = match.get("block_height")
            event["confirmed_block"] = self.current_block
            self.current_round += 1
            confirmed += 1
            print(f"Confirmed coinjoin {event.get('taker')} as {event.get('txid')}")
        return confirmed

    def _active_round_for_taker(self, taker_name: str) -> bool:
        return any(
            event.get("status") == "started" and event.get("taker") == taker_name
            for event in self.joinmarket_round_events
        )

    def _has_active_round(self) -> bool:
        return any(
            event.get("status") == "started"
            for event in self.joinmarket_round_events
        )

    def _started_round_count(self) -> int:
        return len([
            event for event in self.joinmarket_round_events
            if event.get("status") in ("started", "confirmed", "stopped")
        ])

    def _expire_stalled_rounds(self) -> None:
        for event in self.joinmarket_round_events:
            if event.get("status") != "started":
                continue
            age = self.current_block - int(cast(int, event.get("start_block") or 0))
            if age <= JOINMARKET_ROUND_TIMEOUT_BLOCKS:
                continue
            event["status"] = "failed"
            event["stop_block"] = self.current_block
            taker_name = event.get("taker")
            for client in self.clients:
                if client.name == taker_name:
                    client.stop_coinjoin()
                    client.coinjoin_in_process = False
                    break
            raise RuntimeError(
                f"JoinMarket round for {taker_name} did not produce a mined "
                f"destination output within {JOINMARKET_ROUND_TIMEOUT_BLOCKS} blocks"
            )

    def _client_confirmed_balance(self, client: EmulatorClient) -> int:
        try:
            return client.get_balance()
        except Exception as e:
            print(f"- waiting for {client.name} wallet balance ({e})")
            return 0

    def _client_has_confirmed_balance(
        self, client: EmulatorClient, required_sats: int, role: str
    ) -> bool:
        balance = self._client_confirmed_balance(client)
        if balance < required_sats:
            print(
                f"- waiting for JoinMarket {role} {client.name} balance "
                f"({balance}/{required_sats} sats)"
            )
            return False
        return True

    def update_coinjoins_joinmarket(self) -> None:
        self._confirm_started_rounds()
        self._expire_stalled_rounds()

        for client in self.clients:
            client.get_status()

        for client in self.clients:
            if client.type == "maker" and not client.maker_running and client.delay[0] <= self.current_block:
                if not self._client_has_confirmed_balance(client, JOINMARKET_MAKER_MIN_SIZE_SATS, "maker"):
                    continue
                print(f"Starting maker {client.name}")
                client.start_maker(0, 5000, 0.00004, "sw0reloffer", JOINMARKET_MAKER_MIN_SIZE_SATS)
                try:
                    client.get_status()
                except Exception:
                    pass

        running_makers = [
            maker for maker in self.clients
            if maker.type == "maker" and maker.maker_running
        ]
        if len(running_makers) < JOINMARKET_COUNTERPARTIES:
            print(
                f"- waiting for JoinMarket makers "
                f"({len(running_makers)}/{JOINMARKET_COUNTERPARTIES} running)"
            )
            return

        total_started_rounds = self._started_round_count()
        for client in self.clients:
            can_start_more_rounds = self.scenario.rounds == 0 or total_started_rounds < self.scenario.rounds
            if (
                client.type == "taker"
                and not client.coinjoin_in_process
                and client.delay[0] <= self.current_block
                and can_start_more_rounds
                and not self._has_active_round()
                and not self._active_round_for_taker(client.name)
            ):
                if not self._client_has_confirmed_balance(client, JOINMARKET_COINJOIN_AMOUNT_SATS, "taker"):
                    continue
                address = client.get_new_address()
                maker_names = [maker.name for maker in running_makers]
                client.start_coinjoin(0, JOINMARKET_COINJOIN_AMOUNT_SATS, JOINMARKET_COUNTERPARTIES, address)
                client.coinjoin_in_process = True
                client.coinjoin_start = self.current_block
                total_started_rounds += 1
                self.joinmarket_round_events.append({
                    "round_id": total_started_rounds,
                    "engine": "joinmarket",
                    "status": "started",
                    "taker": client.name,
                    "candidate_makers": maker_names,
                    "counterparties": JOINMARKET_COUNTERPARTIES,
                    "amount_sats": JOINMARKET_COINJOIN_AMOUNT_SATS,
                    "mixdepth": 0,
                    "destination_address": address,
                    "start_block": self.current_block,
                    "start_chain_height": self.node.get_block_count() if self.node is not None else None,
                })
                print(f"Starting coinjoin {client.name}")
                break


    def run_engine(self) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
            
        self.update_invoice_payments()
        initial_block = self.node.get_block_count()
        for i in range(5):
            # Takers need 3 confirmations of transactions for the sourcing commitments
            self.node.mine_block()

        while (self.scenario.rounds == 0 or self.current_round < self.scenario.rounds) and (
                self.scenario.blocks == 0 or self.current_block < self.scenario.blocks):
            if (
                self.scenario.blocks == 0
                and self.scenario.rounds > 0
                and self.current_block > (self.scenario.rounds * JOINMARKET_ROUND_TIMEOUT_BLOCKS) + 10
            ):
                raise RuntimeError(
                    f"JoinMarket scenario did not complete {self.scenario.rounds} "
                    f"round(s) within {self.current_block} simulated blocks"
                )

            for _ in range(3):
                try:
                    self.current_block = self.node.get_block_count() - initial_block
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
            if self.scenario.blocks == 0 or self.current_block < self.scenario.blocks:
                self.node.mine_block()
            sleep(JOINMARKET_LOOP_SLEEP_SECONDS)

        print()
        print(f"- limit reached")
        self.node.mine_block(JOINMARKET_FINAL_SETTLE_BLOCKS)
