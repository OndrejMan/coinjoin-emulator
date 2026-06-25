import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from requests.exceptions import ConnectionError as RequestsConnectionError

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
    def engine_args(self, **overrides: object) -> SimpleNamespace:
        args = SimpleNamespace(
            btcFolder="",
            image_prefix="ghcr.io/ondrejman/",
            btc_node_image="",
            joinmarket_client_server_image="",
            irc_server_image="",
            coinjoin_infrastructure_local_build=False,
            force_rebuild=False,
            proxy="",
            control_ip="localhost",
            btc_node_arg=[],
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def test_image_ref_uses_prefix_by_default(self) -> None:
        engine = MinimalEngine(self.engine_args(), Mock(), "/tmp")

        self.assertEqual(engine.image_ref("btc-node"), "ghcr.io/ondrejman/btc-node")

    def test_image_ref_override_wins_over_prefix(self) -> None:
        engine = MinimalEngine(
            self.engine_args(btc_node_image="registry.example/btc-node:test"),
            Mock(),
            "/tmp",
        )

        self.assertEqual(engine.image_ref("btc-node"), "registry.example/btc-node:test")

    def test_prepare_image_local_build_tags_resolved_ref(self) -> None:
        driver = Mock()
        engine = MinimalEngine(
            self.engine_args(
                btc_node_image="registry.example/btc-node:test",
                coinjoin_infrastructure_local_build=True,
            ),
            driver,
            "/tmp",
        )

        engine.prepare_image("btc-node")

        driver.build.assert_called_once_with(
            "registry.example/btc-node:test",
            "./containers/btc-node",
        )

    def test_start_btc_node_passes_optional_bitcoind_args(self) -> None:
        driver = Mock()
        driver.run.return_value = ("btc-node", {18443: 18443, 18444: 18444})
        args = self.engine_args(image_prefix="", btc_node_arg=["-blocksxor=0"])
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
        args = self.engine_args(image_prefix="")
        engine = MinimalEngine(args, driver, "/tmp")

        with patch("manager.engine.engine_base.BtcNode.wait_ready"):
            engine.start_btc_node()

        driver.run.assert_called_once()
        self.assertIsNone(driver.run.call_args.kwargs["command"])

    def test_start_btc_node_uses_driver_control_host_when_available(self) -> None:
        driver = Mock()
        driver.control_host = "127.0.0.1"
        driver.run.return_value = ("10.42.0.10", {18443: 41000, 18444: 41001})
        engine = MinimalEngine(self.engine_args(image_prefix="", control_ip="host.docker.internal"), driver, "/tmp")

        with patch("manager.engine.engine_base.BtcNode") as btc_node_class:
            btc_node_class.return_value.wait_ready.return_value = None
            engine.start_btc_node()

        btc_node_class.assert_called_once_with(
            host="127.0.0.1",
            port=41000,
            internal_ip="10.42.0.10",
            proxy="",
        )
        self.assertIs(engine.node, btc_node_class.return_value)

    def test_start_btc_node_is_not_initialized_when_readiness_fails(self) -> None:
        driver = Mock()
        driver.run.return_value = ("btc-node", {18443: 18443, 18444: 18444})
        engine = MinimalEngine(self.engine_args(image_prefix=""), driver, "/tmp")

        with patch(
            "manager.engine.engine_base.BtcNode.wait_ready",
            side_effect=TimeoutError("not ready"),
        ):
            with self.assertRaisesRegex(TimeoutError, "not ready"):
                engine.start_btc_node()

        self.assertIsNone(engine.node)

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

    def test_stop_coinjoins_continues_when_a_client_connection_is_reset(self) -> None:
        unavailable_client = Mock()
        unavailable_client.name = "wasabi-client-000"
        unavailable_client.stop_coinjoin.side_effect = RequestsConnectionError("connection reset")
        healthy_client = Mock()
        healthy_client.name = "wasabi-client-001"
        engine = MinimalEngine(Mock(), Mock(), "/tmp")
        engine.clients = [unavailable_client, healthy_client]

        engine.stop_coinjoins()

        unavailable_client.stop_coinjoin.assert_called_once_with()
        healthy_client.stop_coinjoin.assert_called_once_with()

    def test_store_logs_writes_only_to_emulator_artifact_directory(self) -> None:
        engine = MinimalEngine(self.engine_args(), Mock(), "/tmp")
        engine.node = Mock()
        engine.node.get_block_count.return_value = 1
        engine.node.get_block_hash.return_value = "block-hash"
        engine.node.get_block_info.return_value = {"height": 0, "tx": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch("manager.engine.engine_base.datetime.datetime") as datetime_mock:
                    datetime_mock.now.return_value.strftime.return_value = "2026-06-20_18-10"
                    engine.store_logs()
                    datetime_mock.now.assert_called_once_with(ZoneInfo("Europe/Prague"))
            finally:
                os.chdir(previous_cwd)

            run_dir = Path(tmpdir) / "logs" / "2026-06-20_18-10_test"
            emulator_dir = run_dir / "coinjoin_emulator_data"
            self.assertTrue((emulator_dir / "scenario.json").is_file())
            self.assertTrue((emulator_dir / "data" / "btc-node" / "block_0.json").is_file())
            self.assertTrue((emulator_dir / "data" / "btc-node" / "block_1.json").is_file())
            self.assertEqual(engine.node.get_block_hash.call_count, 2)
            archive = emulator_dir / "emulation_logs.zip"
            self.assertTrue(archive.is_file())
            self.assertFalse((run_dir / "scenario.json").exists())
            with zipfile.ZipFile(archive) as contents:
                self.assertIn("coinjoin_emulator_data/scenario.json", contents.namelist())

    def test_store_logs_uses_requested_run_timezone(self) -> None:
        engine = MinimalEngine(self.engine_args(run_timezone="UTC"), Mock(), "/tmp")
        engine.node = Mock()
        engine.node.get_block_count.return_value = 0
        engine.node.get_block_hash.return_value = "block-hash"
        engine.node.get_block_info.return_value = {"height": 0, "tx": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch("manager.engine.engine_base.datetime.datetime") as datetime_mock:
                    datetime_mock.now.return_value.strftime.return_value = "2026-06-20_16-10"
                    engine.store_logs()
                    datetime_mock.now.assert_called_once_with(ZoneInfo("UTC"))
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
