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
        self.log_calls = []
        self.peek_calls = []

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
        FakeJoinMarketClientServer.instances.append(self)

    def wait_wallet(self, timeout):
        self.wait_wallet_timeout = timeout
        return self.wait_wallet_result


class FakeBtcNode:
    def __init__(self):
        self.create_wallet_calls = []

    def create_wallet(self, wallet, disable_private_keys=False, allow_descriptor_fallback=True):
        self.create_wallet_calls.append(
            {
                "wallet": wallet,
                "disable_private_keys": disable_private_keys,
                "allow_descriptor_fallback": allow_descriptor_fallback,
            }
        )


def engine_args(proxy=""):
    return SimpleNamespace(
        image_prefix="ghcr.io/ondrejman/",
        proxy=proxy,
        control_ip="host.docker.internal",
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

    def test_engine_creates_legacy_keyed_bitcoin_core_wallet_for_joinmarket(self):
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
                    "disable_private_keys": False,
                    "allow_descriptor_fallback": False,
                }
            ],
        )
        start_irc_server.assert_called_once_with()

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


if __name__ == "__main__":
    unittest.main()
