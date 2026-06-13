import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from manager.engine.configuration import JoinMarketConfig, JoinMarketRole, WalletConfig
from manager.engine.joinmarket_engine import JoinmarketEngine


class FakeDriver:
    def __init__(self):
        self.calls = []
        self.build_calls = []
        self.log_calls = []
        self.peek_calls = []

    def has_image(self, name):
        return True

    def build(self, name, path):
        self.build_calls.append({"name": name, "path": path})

    def run(self, name, image, env=None, ports=None, cpu=0.1, memory=768, **_kwargs):
        self.calls.append(
            {
                "name": name,
                "image": image,
                "env": env,
                "ports": ports,
                "cpu": cpu,
                "memory": memory,
            }
        )
        return f"{name}.pod", {28183: 32083}

    def logs(self, name):
        self.log_calls.append(name)
        return "container stderr"

    def peek(self, name, path):
        self.peek_calls.append((name, path))
        return "jmwalletd stderr"


class FakeJoinMarketClientServer:
    instances = []
    wait_wallet_result = True

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.maker_running = False
        self.coinjoin_in_process = False
        self.coinjoin_start = 0
        self.started_maker = False
        self.started_coinjoins = []
        self.address_counter = 0
        FakeJoinMarketClientServer.instances.append(self)

    def wait_wallet(self, timeout):
        self.wait_wallet_timeout = timeout
        return self.wait_wallet_result

    def get_status(self):
        return {
            "maker_running": self.maker_running,
            "coinjoin_in_process": self.coinjoin_in_process,
        }

    def start_maker(self, txfee, cjfee_a, cjfee_r, ordertype, minsize):
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

    def get_new_address(self):
        self.address_counter += 1
        return f"address-{self.name}-{self.address_counter}"

    def start_coinjoin(self, mixdepth, amount_sats, counterparties, destination):
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

    def stop_coinjoin(self):
        self.coinjoin_in_process = False
        return True


class FakeBtcNode:
    def __init__(self, blocks=None, block_count=200):
        self.create_wallet_calls = []
        self.blocks = blocks or {}
        self.block_count = block_count

    def create_wallet(self, wallet, disable_private_keys=False, allow_descriptor_fallback=True):
        self.create_wallet_calls.append(
            {
                "wallet": wallet,
                "disable_private_keys": disable_private_keys,
                "allow_descriptor_fallback": allow_descriptor_fallback,
            }
        )

    def get_block_count(self):
        if self.blocks:
            return max(self.blocks)
        return self.block_count

    def get_block_hash(self, height):
        return f"block-{height}"

    def get_block_info(self, block_hash):
        height = int(block_hash.removeprefix("block-"))
        return self.blocks.get(height, {"height": height, "tx": []})


def engine_args(proxy=""):
    return SimpleNamespace(
        image_prefix="ghcr.io/ondrejman/",
        proxy=proxy,
        control_ip="host.docker.internal",
        force_rebuild=False,
    )


class JoinmarketEngineTest(unittest.TestCase):
    def setUp(self):
        FakeJoinMarketClientServer.instances = []
        FakeJoinMarketClientServer.wait_wallet_result = True

    def test_distributor_uses_driver_port_mapping_without_proxy(self):
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)

        with patch(
            "manager.engine.joinmarket_engine.JoinMarketClientServer",
            FakeJoinMarketClientServer,
        ):
            engine.start_distributor()

        self.assertEqual(driver.calls[0]["ports"], {28183: 28183})
        distributor = FakeJoinMarketClientServer.instances[0]
        self.assertEqual(distributor.host, "host.docker.internal")
        self.assertEqual(distributor.port, 32083)
        self.assertEqual(distributor.proxy, "")

    def test_distributor_timeout_dumps_container_logs(self):
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
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

    def test_engine_creates_watch_only_bitcoin_core_wallet_for_joinmarket(self):
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        engine.node = FakeBtcNode()

        with patch.object(engine, "start_irc_server") as start_irc_server, patch(
            "manager.engine.joinmarket_engine.sleep"
        ):
            engine.start_engine_infrastructure()

        self.assertEqual(
            engine.node.create_wallet_calls,
            [
                {
                    "wallet": "jm_wallet",
                    "disable_private_keys": True,
                    "allow_descriptor_fallback": True,
                }
            ],
        )
        start_irc_server.assert_called_once_with()

    def test_prepare_images_rebuilds_patched_joinmarket_client_server(self):
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)

        engine.prepare_images()

        self.assertEqual(
            driver.build_calls,
            [
                {
                    "name": "ghcr.io/ondrejman/joinmarket-client-server",
                    "path": "./containers/joinmarket-client-server",
                }
            ],
        )

    def test_client_uses_driver_port_mapping_without_proxy(self):
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
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
        self.assertIs(client, FakeJoinMarketClientServer.instances[0])
        self.assertEqual(client.host, "host.docker.internal")
        self.assertEqual(client.port, 32083)
        self.assertEqual(client.type, "taker")

    def test_client_uses_pod_ip_and_container_port_with_proxy(self):
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(proxy="http://proxy:8080"), driver)
        wallet = WalletConfig(
            funds=[1000],
            joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
        )

        with patch(
            "manager.engine.joinmarket_engine.JoinMarketClientServer",
            FakeJoinMarketClientServer,
        ):
            client = engine.start_client(2, wallet)

        self.assertEqual(driver.calls[0]["ports"], {28183: 28186})
        self.assertEqual(client.host, "jcs-002.pod")
        self.assertEqual(client.port, 28183)
        self.assertEqual(client.proxy, "http://proxy:8080")
        self.assertEqual(client.type, "maker")

    def test_update_starts_makers_before_taker_coinjoin(self):
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        engine.node = FakeBtcNode(block_count=205)
        engine.scenario.rounds = 1
        engine.current_block = 5
        taker = FakeJoinMarketClientServer(name="jcs-000", type="taker", delay=(0, 0))
        makers = [
            FakeJoinMarketClientServer(name=f"jcs-{idx:03}", type="maker", delay=(0, 0))
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

    def test_started_round_is_confirmed_by_mined_destination_output(self):
        driver = FakeDriver()
        engine = JoinmarketEngine(engine_args(), driver)
        engine.node = FakeBtcNode(
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

        engine._confirm_started_rounds()

        self.assertEqual(engine.current_round, 1)
        self.assertEqual(engine.joinmarket_round_events[0]["status"], "confirmed")
        self.assertEqual(engine.joinmarket_round_events[0]["txid"], "joinmarket-tx")
        self.assertEqual(engine.joinmarket_round_events[0]["block_height"], 206)


if __name__ == "__main__":
    unittest.main()
