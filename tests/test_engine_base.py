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
from manager.exceptions import RpcError, StartupError


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

    def test_start_btc_node_forwards_shared_storage_identity(self) -> None:
        driver = Mock()
        driver.run.return_value = ("btc-node", {18443: 18443, 18444: 18444})
        engine = MinimalEngine(
            self.engine_args(btcFolder="/storage/user/btc-data"),
            driver,
            "/tmp",
        )

        with (
            patch.dict(
                os.environ,
                {"KUBERNETES_STORAGE_UID": "1234", "KUBERNETES_STORAGE_GID": "5678"},
            ),
            patch("manager.engine.engine_base.BtcNode.wait_ready"),
        ):
            engine.start_btc_node()

        self.assertEqual(
            driver.run.call_args.kwargs["volumes"],
            {
                "/storage/user/btc-data": {
                    "bind": "/home/bitcoin/data",
                    "mode": "rw",
                    "uid": "1234",
                    "gid": "5678",
                }
            },
        )
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

    def test_start_clients_accepts_success_on_final_retry(self) -> None:
        engine = MinimalEngine(self.engine_args(), Mock(), "/tmp")
        wallet = WalletConfig(funds=[])
        client = Mock()

        with (
            patch.object(engine, "start_client", side_effect=[None, None, None, client]) as start_client,
            patch("manager.engine.engine_base.sleep"),
        ):
            engine.start_clients([wallet])

        self.assertEqual(engine.clients, [client])
        self.assertEqual(start_client.call_count, 4)

    def test_start_clients_raises_after_retry_budget_is_exhausted(self) -> None:
        engine = MinimalEngine(self.engine_args(), Mock(), "/tmp")
        wallet = WalletConfig(funds=[])

        with (
            patch.object(engine, "start_client", return_value=None) as start_client,
            patch("manager.engine.engine_base.sleep"),
            self.assertRaisesRegex(RuntimeError, "Failed to start 1 client"),
        ):
            engine.start_clients([wallet])

        self.assertEqual(engine.clients, [])
        self.assertEqual(start_client.call_count, 4)

    def test_validate_clients_fails_without_restarting_unavailable_client(self) -> None:
        driver = Mock()
        engine = MinimalEngine(self.engine_args(), driver, "/tmp")
        engine.scenario.wallets = [WalletConfig(funds=[])]
        client = Mock()
        client.name = "wasabi-client-002"
        client.wait_wallet.return_value = False
        engine.clients = [client]

        with (
            patch("manager.engine.engine_base.CLIENT_HEALTHCHECK_TIMEOUT", 1),
            self.assertRaisesRegex(
                RuntimeError,
                "Client RPC health-check failed before funding: wasabi-client-002",
            ),
        ):
            engine.validate_clients()

        client.wait_wallet.assert_called_once_with(timeout=1)
        driver.stop.assert_not_called()

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

    def test_fund_distributor_uses_bounded_balance_rpc_and_succeeds(self) -> None:
        engine = MinimalEngine(Mock(), Mock(), "/tmp")
        engine.node = Mock()
        engine.distributor = Mock()
        engine.distributor.get_new_address.return_value = "bcrt1distributor"
        engine.distributor.get_balance.side_effect = [0, 2 * 100_000_000]

        with patch("manager.engine.engine_base.sleep"):
            engine.fund_distributor(2)

        self.assertEqual(engine.node.fund_address.call_count, 10)
        self.assertEqual(engine.distributor.get_balance.call_count, 2)
        engine.distributor.get_balance.assert_called_with(timeout=5)

    def test_fund_distributor_times_out_with_progress_and_endpoint(self) -> None:
        engine = MinimalEngine(Mock(), Mock(), "/tmp")
        engine.node = Mock()
        engine.distributor = Mock()
        engine.distributor.name = "wasabi-client-distributor"
        engine.distributor.host = "127.0.0.1"
        engine.distributor.port = 37128
        engine.distributor.get_new_address.return_value = "bcrt1distributor"
        engine.distributor.get_balance.side_effect = RequestsConnectionError(
            "coordinator endpoint is unreachable"
        )
        clock = [0.0]

        def advance(seconds: float) -> None:
            clock[0] += seconds

        with (
            patch("manager.engine.engine_base.DISTRIBUTOR_FUNDING_TIMEOUT", 3),
            patch("manager.engine.engine_base.DISTRIBUTOR_FUNDING_PROGRESS_INTERVAL", 1),
            patch("manager.engine.engine_base.monotonic", side_effect=lambda: clock[0]),
            patch("manager.engine.engine_base.sleep", side_effect=advance),
            patch("manager.engine.engine_base.log.info") as info,
            self.assertRaisesRegex(
                StartupError,
                r"endpoint=wasabi-client-distributor@127\.0\.0\.1:37128.*"
                r"last balance error=coordinator endpoint is unreachable",
            ),
        ):
            engine.fund_distributor(2)

        self.assertTrue(any("still funding distributor" in call.args[0] for call in info.call_args_list))

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

    def test_store_logs_uses_requested_run_id(self) -> None:
        engine = MinimalEngine(self.engine_args(run_id="wasabi-test-001"), Mock(), "/tmp")
        engine.node = Mock()
        engine.node.get_block_count.return_value = 0
        engine.node.get_block_hash.return_value = "block-hash"
        engine.node.get_block_info.return_value = {"height": 0, "tx": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                engine.store_logs()
            finally:
                os.chdir(previous_cwd)
            self.assertTrue((Path(tmpdir) / "logs/wasabi-test-001/coinjoin_emulator_data/scenario.json").is_file())

    def test_store_logs_archives_healthy_clients_when_one_client_is_unavailable(self) -> None:
        engine = MinimalEngine(self.engine_args(run_id="partial-client-logs"), Mock(), "/tmp")
        engine.node = Mock()
        engine.node.get_block_count.return_value = 0
        engine.node.get_block_hash.return_value = "block-hash"
        engine.node.get_block_info.return_value = {"height": 0, "tx": []}
        unavailable = Mock(name="unavailable")
        unavailable.name = "wasabi-client-002"
        healthy = Mock(name="healthy")
        healthy.name = "wasabi-client-003"
        engine.clients = [unavailable, healthy]

        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch.object(
                    engine,
                    "store_client_logs",
                    side_effect=[OSError("pod not found"), None],
                ) as store_client_logs:
                    engine.store_logs()
            finally:
                os.chdir(previous_cwd)

            archive = (
                Path(tmpdir)
                / "logs/partial-client-logs/coinjoin_emulator_data/emulation_logs.zip"
            )
            self.assertTrue(archive.is_file())
            self.assertEqual(store_client_logs.call_count, 2)


if __name__ == "__main__":
    unittest.main()
