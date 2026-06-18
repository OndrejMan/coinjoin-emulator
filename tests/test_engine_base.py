import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.engine.engine_base import EngineBase
from manager.exceptions import RpcError


class MinimalEngine(EngineBase):
    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig(name="test", rounds=0, blocks=0, default_version="test", wallets=[])

    def prepare_images(self) -> None:
        pass

    def start_engine_infrastructure(self) -> None:
        pass

    def start_distributor(self) -> None:
        pass

    def init_client(self) -> object:
        pass

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> None:
        return None

    def stop_client(self, idx: int) -> None:
        pass

    def store_engine_logs(self, data_path: str) -> None:
        pass

    def run_engine(self) -> None:
        pass


class EngineBaseTest(unittest.TestCase):
    def test_start_btc_node_passes_optional_bitcoind_args(self) -> None:
        driver = Mock()
        driver.run.return_value = ("btc-node", {18443: 18443, 18444: 18444})
        args = SimpleNamespace(
            btcFolder="",
            image_prefix="",
            proxy="",
            control_ip="localhost",
            btc_node_arg=["-blocksxor=0"],
        )
        engine = MinimalEngine(args, driver, "/tmp")

        with patch("manager.engine.engine_base.BtcNode.wait_ready"):
            engine.start_btc_node()

        driver.run.assert_called_once()
        self.assertEqual(
            driver.run.call_args.kwargs["command"],
            ["./run.sh", "-blocksxor=0"],
        )

    def test_start_btc_node_uses_image_default_command_without_extra_args(self) -> None:
        driver = Mock()
        driver.run.return_value = ("btc-node", {18443: 18443, 18444: 18444})
        args = SimpleNamespace(
            btcFolder="",
            image_prefix="",
            proxy="",
            control_ip="localhost",
            btc_node_arg=[],
        )
        engine = MinimalEngine(args, driver, "/tmp")

        with patch("manager.engine.engine_base.BtcNode.wait_ready"):
            engine.start_btc_node()

        driver.run.assert_called_once()
        self.assertIsNone(driver.run.call_args.kwargs["command"])

    def test_failed_invoice_payment_remains_pending(self) -> None:
        engine = MinimalEngine(Mock(), Mock(), "/tmp")
        engine.current_block = 0
        engine.current_round = 0
        engine.invoices = {(0, 0): [("bcrt1destination", 100000)]}
        engine.distributor = Mock()
        engine.distributor.send.side_effect = RpcError("direct-send failed")

        with self.assertRaisesRegex(Exception, "Invoice payment failed"):
            engine.update_invoice_payments()

        self.assertEqual(engine.invoices, {(0, 0): [("bcrt1destination", 100000)]})


if __name__ == "__main__":
    unittest.main()
