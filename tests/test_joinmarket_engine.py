import unittest
from types import SimpleNamespace
from typing import ClassVar, cast
from unittest.mock import patch

# pylint: disable=protected-access
from manager.btc_node import BtcNode
from manager.engine.configuration import JoinMarketConfig, JoinMarketRole, WalletConfig
from manager.engine.joinmarket_engine import JoinmarketEngine


class FakeDriver:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.build_calls: list[dict[str, str]] = []
        self.log_calls: list[str] = []
        self.peek_calls: list[tuple[str, str]] = []

    def has_image(self, _name: str) -> bool:
        return True

    def build(self, name: str, path: str) -> None:
        self.build_calls.append({"name": name, "path": path})

    def pull(self, name: str) -> None:
        pass

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
        command: list[str] | None = None,
    ) -> tuple[str, dict[int, int]]:
        self.calls.append(
            {
                "name": name,
                "image": image,
                "env": env,
                "ports": ports,
                "skip_ip": skip_ip,
                "cpu": cpu,
                "memory": memory,
                "volumes": volumes,
                "command": command,
            }
        )
        return f"{name}.pod", {28183: 32083}

    def stop(self, name: str) -> None:
        pass

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        pass

    def logs(self, name: str) -> str:
        self.log_calls.append(name)
        return "container stderr"

    def peek(self, name: str, path: str) -> str:
        self.peek_calls.append((name, path))
        return "jmwalletd stderr"

    def upload(self, name: str, src_path: str, dst_path: str) -> None:
        pass

    def cleanup(self, image_prefix: str = "") -> None:
        pass


class FakeJoinMarketClientServer:
    instances: ClassVar[list["FakeJoinMarketClientServer"]] = []
    wait_wallet_result = True

    def __init__(
        self,
        name: str = "",
        host: str = "",
        port: int = 0,
        proxy: str = "",
        role: str = "maker",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
    ) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.proxy = proxy
        self.type = role
        self.delay = delay
        self.stop = stop
        self.maker_running = False
        self.coinjoin_in_process = False
        self.coinjoin_start = 0
        self.started_maker = False
        self.started_coinjoins: list[dict[str, object]] = []
        self.address_counter = 0
        self.balance = 1000000
        self.wait_wallet_timeout: int | None = None
        self.maker_config: dict[str, int | str | float] = {}
        FakeJoinMarketClientServer.instances.append(self)

    def wait_wallet(self, timeout: int | None) -> bool:
        self.wait_wallet_timeout = timeout
        return self.wait_wallet_result

    def get_status(self) -> dict[str, object]:
        return {
            "maker_running": self.maker_running,
            "coinjoin_in_process": self.coinjoin_in_process,
        }

    def get_balance(self) -> int:
        return self.balance

    def start_maker(
        self,
        txfee: int | str,
        cjfee_a: int | str,
        cjfee_r: float | str,
        ordertype: str,
        minsize: int | str,
    ) -> dict[str, object]:
        self.started_maker = True
        self.maker_running = True
        self.maker_config = {
            "txfee": txfee,
            "cjfee_a": cjfee_a,
            "cjfee_r": cjfee_r,
            "ordertype": ordertype,
            "minsize": minsize,
        }
        return {}

    def get_new_address(self) -> str:
        self.address_counter += 1
        return f"address-{self.name}-{self.address_counter}"

    def list_coins(self) -> object:
        return []

    def list_unspent_coins(self) -> object:
        return []

    def list_keys(self) -> object:
        return []

    def start_coinjoin(
        self, mixdepth: int, amount_sats: int, counterparties: int, destination: str
    ) -> dict[str, object]:
        self.coinjoin_in_process = True
        self.started_coinjoins.append(
            {
                "mixdepth": mixdepth,
                "amount_sats": amount_sats,
                "counterparties": counterparties,
                "destination": destination,
            }
        )
        return {}

    def stop_coinjoin(self) -> bool:
        self.coinjoin_in_process = False
        return True


class FakeBtcNode:
    def __init__(
        self,
        blocks: dict[int, dict[str, object]] | None = None,
        block_count: int = 200,
    ) -> None:
        self.create_wallet_calls: list[dict[str, object]] = []
        self.blocks = blocks or {}
        self.block_count = block_count
        self.fund_address_calls: list[dict[str, object]] = []
        self.mine_block_calls: list[int] = []

    def create_wallet(
        self,
        wallet: str,
        disable_private_keys: bool = False,
        allow_descriptor_fallback: bool = True,
    ) -> None:
        self.create_wallet_calls.append(
            {
                "wallet": wallet,
                "disable_private_keys": disable_private_keys,
                "allow_descriptor_fallback": allow_descriptor_fallback,
            }
        )

    def get_block_count(self) -> int:
        if self.blocks:
            return max(self.blocks)
        return self.block_count

    def get_block_hash(self, height: int) -> str:
        return f"block-{height}"

    def get_block_info(self, block_hash: str) -> dict[str, object]:
        height = int(block_hash.removeprefix("block-"))
        return self.blocks.get(height, {"height": height, "tx": []})

    def fund_address(self, address: str, amount: int | float) -> None:
        self.fund_address_calls.append({"address": address, "amount": amount})

    def mine_block(self, count: int = 1) -> bool:
        self.mine_block_calls.append(count)
        self.block_count += count
        return True


def engine_args(proxy: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        image_prefix="ghcr.io/ondrejman/",
        btc_node_image="",
        joinmarket_client_server_image="",
        irc_server_image="",
        coinjoin_infrastructure_local_build=False,
        proxy=proxy,
        control_ip="host.docker.internal",
        force_rebuild=False,
        joinmarket_descriptor_regtest_fallback=False,
    )


def set_fake_node(engine: JoinmarketEngine, node: FakeBtcNode | None = None) -> FakeBtcNode:
    fake_node = node or FakeBtcNode()
    engine.node = cast(BtcNode, fake_node)
    return fake_node


class JoinmarketEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeJoinMarketClientServer.instances = []
        FakeJoinMarketClientServer.wait_wallet_result = True

    def test_distributor_uses_driver_port_mapping_without_proxy(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        node = set_fake_node(engine)

        with patch(
            "manager.engine.joinmarket_engine.JoinMarketClientServer",
            FakeJoinMarketClientServer,
        ):
            engine.start_distributor()

        self.assertEqual(driver.calls[0]["ports"], {28183: 28183})
        self.assertEqual(
            driver.calls[0]["env"],
            {
                "JM_RPC_WALLET_FILE": "jm_wallet_distributor",
                "JM_DESCRIPTOR_REGTEST_FALLBACK": "0",
            },
        )
        self.assertEqual(
            node.create_wallet_calls,
            [
                {
                    "wallet": "jm_wallet_distributor",
                    "disable_private_keys": True,
                    "allow_descriptor_fallback": True,
                }
            ],
        )
        distributor = FakeJoinMarketClientServer.instances[0]
        self.assertEqual(distributor.host, "host.docker.internal")
        self.assertEqual(distributor.port, 32083)
        self.assertEqual(distributor.proxy, "")

    def test_distributor_timeout_dumps_container_logs(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        set_fake_node(engine)
        FakeJoinMarketClientServer.wait_wallet_result = False

        with patch(
            "manager.engine.joinmarket_engine.JoinMarketClientServer",
            FakeJoinMarketClientServer,
        ):
            with self.assertRaisesRegex(Exception, "Could not start distributor"):
                engine.start_distributor()

        self.assertEqual(driver.log_calls, ["joinmarket-distributor"])
        self.assertEqual(
            driver.peek_calls,
            [("joinmarket-distributor", "/home/joinmarket/jmwalletd.log")],
        )

    def test_engine_starts_irc_without_shared_joinmarket_core_wallet(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        node = set_fake_node(engine)

        with patch.object(engine, "start_irc_server") as start_irc_server, patch(
            "manager.engine.joinmarket_engine.sleep"
        ):
            engine.start_engine_infrastructure()

        self.assertEqual(node.create_wallet_calls, [])
        start_irc_server.assert_called_once_with()

    def test_prepare_images_reuses_joinmarket_client_server_by_default(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)

        engine.prepare_images()

        self.assertEqual(driver.build_calls, [])

    def test_prepare_images_can_rebuild_joinmarket_infrastructure_images(self) -> None:
        driver = FakeDriver()
        args = engine_args()
        args.coinjoin_infrastructure_local_build = True
        engine = JoinmarketEngine(args, driver)

        engine.prepare_images()

        self.assertEqual(
            driver.build_calls,
            [
                {
                    "name": "ghcr.io/ondrejman/btc-node",
                    "path": "./containers/btc-node",
                },
                {
                    "name": "ghcr.io/ondrejman/joinmarket-client-server",
                    "path": "./containers/joinmarket-client-server",
                },
                {
                    "name": "ghcr.io/ondrejman/irc-server",
                    "path": "./containers/irc-server",
                },
            ],
        )

    def test_joinmarket_infrastructure_uses_exact_image_overrides(self) -> None:
        driver = FakeDriver()
        args = engine_args()
        args.irc_server_image = "registry.example/irc-server:test"
        args.joinmarket_client_server_image = "registry.example/jm-client:test"
        engine = JoinmarketEngine(args, driver)
        node = set_fake_node(engine)

        with patch.object(engine, "init_joinmarket_clientserver", FakeJoinMarketClientServer):
            engine.start_irc_server()
            engine.start_distributor()
            engine.start_client(0, WalletConfig(funds=[], joinmarket=None))

        self.assertEqual(node.create_wallet_calls[0]["wallet"], "jm_wallet_distributor")
        self.assertEqual(driver.calls[0]["image"], "registry.example/irc-server:test")
        self.assertEqual(driver.calls[1]["image"], "registry.example/jm-client:test")
        self.assertEqual(driver.calls[2]["image"], "registry.example/jm-client:test")

    def test_client_uses_driver_port_mapping_without_proxy(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        node = set_fake_node(engine)
        wallet = WalletConfig(
            funds=[1000],
            joinmarket=JoinMarketConfig(role=JoinMarketRole.TAKER),
        )

        with patch(
            "manager.engine.joinmarket_engine.JoinMarketClientServer",
            FakeJoinMarketClientServer,
        ):
            client = engine.start_client(0, wallet)

        self.assertEqual(driver.calls[0]["ports"], {28183: 28184})
        self.assertEqual(
            driver.calls[0]["env"],
            {
                "JM_RPC_WALLET_FILE": "jm_wallet_jcs_000",
                "JM_DESCRIPTOR_REGTEST_FALLBACK": "0",
            },
        )
        self.assertEqual(
            node.create_wallet_calls,
            [
                {
                    "wallet": "jm_wallet_jcs_000",
                    "disable_private_keys": True,
                    "allow_descriptor_fallback": True,
                }
            ],
        )
        self.assertIs(client, FakeJoinMarketClientServer.instances[0])
        self.assertIsNotNone(client)
        assert client is not None
        self.assertEqual(client.host, "host.docker.internal")
        self.assertEqual(client.port, 32083)
        self.assertEqual(client.type, "taker")

    def test_client_uses_pod_ip_and_container_port_with_proxy(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(proxy="http://proxy:8080"), driver)
        set_fake_node(engine)
        wallet = WalletConfig(
            funds=[1000],
            joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
        )

        with patch(
            "manager.engine.joinmarket_engine.JoinMarketClientServer",
            FakeJoinMarketClientServer,
        ):
            client = engine.start_client(2, wallet)

        self.assertIsNotNone(client)
        assert client is not None
        self.assertEqual(driver.calls[0]["ports"], {28183: 28186})
        self.assertEqual(
            driver.calls[0]["env"],
            {
                "JM_RPC_WALLET_FILE": "jm_wallet_jcs_002",
                "JM_DESCRIPTOR_REGTEST_FALLBACK": "0",
            },
        )
        self.assertEqual(client.host, "jcs-002.pod")
        self.assertEqual(client.port, 28183)
        self.assertEqual(client.proxy, "http://proxy:8080")
        self.assertEqual(client.type, "maker")

    def test_update_starts_makers_before_taker_coinjoin(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        set_fake_node(engine, FakeBtcNode(block_count=205))
        engine.scenario.rounds = 1
        engine.current_block = 5
        taker = FakeJoinMarketClientServer(name="jcs-000", role="taker", delay=(0, 0))
        makers = [
            FakeJoinMarketClientServer(name=f"jcs-{idx:03}", role="maker", delay=(0, 0))
            for idx in range(1, 5)
        ]
        engine.clients = [taker, *makers]

        engine.update_coinjoins_joinmarket()

        self.assertTrue(all(maker.started_maker for maker in makers))
        self.assertEqual(
            taker.started_coinjoins,
            [
                {
                    "mixdepth": 0,
                    "amount_sats": 40000,
                    "counterparties": 4,
                    "destination": "address-jcs-000-1",
                }
            ],
        )
        self.assertEqual(
            engine.joinmarket_round_events[0]["candidate_makers"],
            ["jcs-001", "jcs-002", "jcs-003", "jcs-004"],
        )

    def test_update_does_not_start_parallel_taker_rounds(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        set_fake_node(engine, FakeBtcNode(block_count=205))
        engine.scenario.rounds = 3
        engine.current_block = 6
        first_taker = FakeJoinMarketClientServer(name="jcs-000", role="taker", delay=(0, 0))
        second_taker = FakeJoinMarketClientServer(name="jcs-001", role="taker", delay=(0, 0))
        first_taker.coinjoin_in_process = True
        makers = [
            FakeJoinMarketClientServer(name=f"jcs-{idx:03}", role="maker", delay=(0, 0))
            for idx in range(2, 6)
        ]
        for maker in makers:
            maker.maker_running = True
        engine.clients = [first_taker, second_taker, *makers]
        engine.joinmarket_round_events = [
            {
                "round_id": 1,
                "status": "started",
                "taker": "jcs-000",
                "destination_address": "destination-address",
                "start_block": 5,
                "start_chain_height": 205,
            }
        ]

        engine.update_coinjoins_joinmarket()

        self.assertEqual(first_taker.started_coinjoins, [])
        self.assertEqual(second_taker.started_coinjoins, [])
        self.assertEqual(len(engine.joinmarket_round_events), 1)

    def test_stalled_round_is_failed_and_new_attempt_can_start(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        set_fake_node(engine, FakeBtcNode(block_count=390))
        engine.scenario.rounds = 1
        engine.current_block = 186
        taker = FakeJoinMarketClientServer(name="jcs-000", role="taker", delay=(0, 0))
        taker.coinjoin_in_process = True
        makers = [
            FakeJoinMarketClientServer(name=f"jcs-{idx:03}", role="maker", delay=(0, 0))
            for idx in range(1, 5)
        ]
        for maker in makers:
            maker.maker_running = True
        engine.clients = [taker, *makers]
        engine.joinmarket_round_events = [
            {
                "round_id": 1,
                "status": "started",
                "taker": "jcs-000",
                "destination_address": "stalled-destination",
                "start_block": 5,
                "start_chain_height": 205,
            }
        ]

        engine.update_coinjoins_joinmarket()

        self.assertEqual(engine.joinmarket_round_events[0]["status"], "failed")
        self.assertEqual(engine.joinmarket_round_events[0]["stop_block"], 186)
        self.assertEqual(engine.joinmarket_round_events[1]["round_id"], 2)
        self.assertEqual(engine.joinmarket_round_events[1]["status"], "started")
        self.assertEqual(taker.started_coinjoins[-1]["destination"], "address-jcs-000-1")

    def test_inactive_taker_round_is_failed_and_new_attempt_can_start(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        set_fake_node(engine, FakeBtcNode(block_count=210))
        engine.scenario.rounds = 1
        engine.current_block = 8
        taker = FakeJoinMarketClientServer(name="jcs-000", role="taker", delay=(0, 0))
        makers = [
            FakeJoinMarketClientServer(name=f"jcs-{idx:03}", role="maker", delay=(0, 0))
            for idx in range(1, 5)
        ]
        for maker in makers:
            maker.maker_running = True
        engine.clients = [taker, *makers]
        engine.joinmarket_round_events = [
            {
                "round_id": 1,
                "status": "started",
                "taker": "jcs-000",
                "destination_address": "dead-destination",
                "start_block": 7,
                "start_chain_height": 205,
            }
        ]

        engine.update_coinjoins_joinmarket()

        self.assertEqual(engine.joinmarket_round_events[0]["status"], "failed")
        self.assertEqual(
            engine.joinmarket_round_events[0]["failure_reason"],
            "taker service stopped before a mined destination output was found",
        )
        self.assertEqual(engine.joinmarket_round_events[1]["round_id"], 2)
        self.assertEqual(engine.joinmarket_round_events[1]["status"], "started")

    def test_update_waits_for_maker_confirmed_balance_before_starting(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        set_fake_node(engine, FakeBtcNode(block_count=205))
        engine.scenario.rounds = 1
        engine.current_block = 5
        taker = FakeJoinMarketClientServer(name="jcs-000", role="taker", delay=(0, 0))
        maker = FakeJoinMarketClientServer(name="jcs-001", role="maker", delay=(0, 0))
        maker.balance = 0
        engine.clients = [taker, maker]

        engine.update_coinjoins_joinmarket()

        self.assertFalse(maker.started_maker)

    def test_started_round_is_confirmed_by_mined_destination_output(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        set_fake_node(
            engine,
            FakeBtcNode(
                block_count=207,
                blocks={
                    206: {
                        "height": 206,
                        "tx": [
                            {
                                "txid": "joinmarket-tx",
                                "vout": [
                                    {
                                        "n": 0,
                                        "value": 0.0004,
                                        "scriptPubKey": {"address": "destination-address"},
                                    }
                                ],
                            }
                        ],
                    }
                },
            ),
        )
        engine.current_block = 6
        engine.joinmarket_round_events = [
            {
                "round_id": 1,
                "status": "started",
                "taker": "jcs-000",
                "destination_address": "destination-address",
                "start_block": 5,
                "start_chain_height": 205,
            }
        ]

        engine.confirm_started_rounds()

        self.assertEqual(engine.current_round, 1)
        self.assertEqual(engine.joinmarket_round_events[0]["status"], "confirmed")
        self.assertEqual(engine.joinmarket_round_events[0]["txid"], "joinmarket-tx")
        self.assertEqual(engine.joinmarket_round_events[0]["block_height"], 206)

    def test_joinmarket_invoice_funding_uses_bitcoin_core_directly(self) -> None:
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        node = set_fake_node(engine)

        engine.pay_invoices([
            ("bcrt1maker", 1000000),
            ("bcrt1taker", 200000),
        ])

        self.assertEqual(
            node.fund_address_calls,
            [
                {"address": "bcrt1maker", "amount": 0.01},
                {"address": "bcrt1taker", "amount": 0.002},
            ],
        )
        self.assertEqual(node.mine_block_calls, [1])


if __name__ == "__main__":
    unittest.main()
