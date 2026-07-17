from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

from manager.btc_node import BtcNode
from manager.engine.configuration import WalletConfig
from manager.engine.wasabi_engine import (
    WASABI_CLIENT_DATA_PATH,
    WASABI_CLIENT_START_TIMEOUT_SECONDS,
    WASABI_COORDINATOR_LOG_PATH,
    WASABI_COORDINATOR_START_TIMEOUT_SECONDS,
    WASABI_SETTLEMENT_BLOCKS_AFTER_LIMIT,
    WasabiEngine,
    version_at_least,
)
from manager.exceptions import StartupError
from manager.wasabi_backend_factory import BackendArchitecture

# pylint: disable=protected-access


def engine_args() -> SimpleNamespace:
    return SimpleNamespace(
        image_prefix="ghcr.io/ondrejman/",
        btc_node_ip="",
        wasabi_backend_ip="",
        proxy="",
        control_ip="127.0.0.1",
    )


def configured_engine(architecture: BackendArchitecture) -> tuple[WasabiEngine, Mock, Mock]:
    driver = Mock()
    driver.control_host = "127.0.0.1"
    driver.run.return_value = ("10.42.0.20", {37128: 30123})
    engine = WasabiEngine(engine_args(), driver)
    engine.backend_architecture = architecture
    node = Mock()
    node.internal_ip = "10.42.0.2"
    engine.node = cast(BtcNode, node)
    engine.backend = SimpleNamespace(internal_ip="10.42.0.3")
    distributor = Mock()
    distributor.wait_wallet.return_value = True
    engine.init_wasabi_client = Mock(return_value=distributor)  # type: ignore[method-assign]
    return engine, driver, distributor


def test_split_distributor_receives_coordinator_internal_ip() -> None:
    engine, driver, distributor = configured_engine(BackendArchitecture.SPLIT)
    engine.coordinator = SimpleNamespace(internal_ip="10.42.0.4")

    engine.start_distributor()

    assert driver.run.call_args.kwargs["env"]["ADDR_WASABI_COORDINATOR"] == "10.42.0.4"
    distributor.wait_wallet.assert_called_once_with(timeout=360)


def test_split_distributor_fails_before_start_when_coordinator_is_missing() -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.SPLIT)

    with pytest.raises(StartupError, match="coordinator is not initialized"):
        engine.start_distributor()

    driver.run.assert_not_called()


def test_legacy_distributor_environment_is_unchanged() -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.LEGACY)

    engine.start_distributor()

    assert "ADDR_WASABI_COORDINATOR" not in driver.run.call_args.kwargs["env"]


def test_client_readiness_allows_slow_kubernetes_startup() -> None:
    engine, _, client = configured_engine(BackendArchitecture.SPLIT)
    engine.scenario.default_version = "2.6.0"

    started_client = engine.start_client(1, WalletConfig(funds=[]))

    assert started_client is client
    client.wait_wallet.assert_called_once_with(timeout=WASABI_CLIENT_START_TIMEOUT_SECONDS)
    assert WASABI_CLIENT_START_TIMEOUT_SECONDS == 180


def test_wasabi_clients_capture_the_client_data_directory() -> None:
    engine, _, _ = configured_engine(BackendArchitecture.SPLIT)

    assert engine.log_src_path == WASABI_CLIENT_DATA_PATH


def test_split_round_count_uses_unique_successful_broadcasts() -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.SPLIT)
    txid_one = "a" * 64
    txid_two = "B" * 64
    driver.peek.return_value = "\n".join(
        [
            "Round (attempt): Phase changed: OutputRegistration -> TransactionSigning",
            f"Round (one): Successfully broadcast the coinjoin: {txid_one}.",
            "Round (failed): Not all participants signed. Creating blame round.",
            f"Round (one-repeated): Successfully broadcast the coinjoin: {txid_one}.",
            f"Round (two): Successfully broadcasted the coinjoin: {txid_two}.",
        ]
    )

    assert engine._get_current_round() == 2
    driver.peek.assert_called_once_with("wasabi-coordinator", WASABI_COORDINATOR_LOG_PATH)


def test_split_round_count_does_not_count_signing_or_failed_rounds() -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.SPLIT)
    driver.peek.return_value = "\n".join(
        [
            "Round (attempt): Phase changed: OutputRegistration -> TransactionSigning",
            "Round (attempt): Not all participants signed. Creating blame round.",
        ]
    )

    assert engine._get_current_round() == 0


def test_legacy_round_count_allows_lazily_created_store() -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.LEGACY)
    driver.peek.return_value = ""

    assert engine._get_current_round() == 0
    driver.peek.assert_called_once_with(
        "wasabi-backend",
        "/home/wasabi/.walletwasabi/backend/WabiSabi/CoinJoinIdStore.txt",
        missing_ok=True,
    )


@pytest.mark.parametrize("version", ["2.0.3", "2.0.3-rc1", "2.0.10"])
def test_version_at_least_keeps_numeric_release_prefix(version: str) -> None:
    assert version_at_least(version, "2.0.3")


def test_client_start_requests_low_cpu_with_burst_limit() -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.SPLIT)
    engine.coordinator = SimpleNamespace(internal_ip="10.42.0.4")
    engine.versions = {"2.6.0"}
    client = Mock()
    client.wait_wallet.return_value = True

    with (
        patch("manager.engine.wasabi_engine.sleep"),
        patch.object(engine, "init_wasabi_client", return_value=client),
    ):
        assert engine.start_client(0, WalletConfig(funds=[1000000])) is client

    run_kwargs = driver.run.call_args.kwargs
    assert run_kwargs["cpu"] == 1.0
    assert run_kwargs["cpu_request"] == 0.1
    assert run_kwargs["memory"] == 768


def test_coordinator_timeout_includes_container_logs() -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.SPLIT)
    coordinator = Mock()
    coordinator.wait_ready.side_effect = TimeoutError("coordinator endpoint unavailable")
    driver.logs.return_value = "CRITICAL Program.Main (20) System.IO.IOException: disk full"

    with (
        patch("manager.engine.wasabi_engine.sleep"),
        patch("manager.engine.wasabi_engine.create_coordinator", return_value=coordinator),
    ):
        with pytest.raises(StartupError, match="disk full"):
            engine.start_wasabi_coordinator()

    coordinator.wait_ready.assert_called_once_with(
        timeout=WASABI_COORDINATOR_START_TIMEOUT_SECONDS
    )
    driver.logs.assert_called_once_with("wasabi-coordinator")
    driver.stop.assert_not_called()
    assert WASABI_COORDINATOR_START_TIMEOUT_SECONDS == 120


def test_coordinator_restarts_once_after_node_sync_race() -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.SPLIT)
    coordinator = Mock()
    coordinator.wait_ready.side_effect = [TimeoutError("coordinator endpoint unavailable"), None]
    driver.logs.return_value = "CRITICAL Bitcoin Node is not fully synchronized."

    with (
        patch("manager.engine.wasabi_engine.sleep"),
        patch("manager.engine.wasabi_engine.create_coordinator", return_value=coordinator),
    ):
        engine.start_wasabi_coordinator()

    assert coordinator.wait_ready.call_count == 2
    assert engine.coordinator is coordinator
    lifecycle_calls = [name for name, _, _ in driver.method_calls if name in {"run", "stop"}]
    assert lifecycle_calls == ["run", "stop", "run"]
    driver.stop.assert_called_once_with("wasabi-coordinator")
    node = cast(Mock, engine.node)
    assert node.wait_synchronized_quiet.call_count == 2


def test_coordinator_sync_race_fails_after_second_attempt() -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.SPLIT)
    coordinator = Mock()
    coordinator.wait_ready.side_effect = TimeoutError("coordinator endpoint unavailable")
    driver.logs.return_value = "CRITICAL Bitcoin Node is not fully synchronized."

    with (
        patch("manager.engine.wasabi_engine.sleep"),
        patch("manager.engine.wasabi_engine.create_coordinator", return_value=coordinator),
    ):
        with pytest.raises(StartupError, match="Bitcoin Node is not fully synchronized"):
            engine.start_wasabi_coordinator()

    assert driver.run.call_count == 2
    assert coordinator.wait_ready.call_count == 2
    driver.stop.assert_called_once_with("wasabi-coordinator")


def test_run_engine_mines_settlement_blocks_after_limit() -> None:
    engine, _, _ = configured_engine(BackendArchitecture.SPLIT)
    node = Mock()
    node.get_block_count.side_effect = [100, 101]
    node.mine_block.return_value = True
    engine.node = cast(BtcNode, node)
    engine.scenario.rounds = 0
    engine.scenario.blocks = 1
    engine._get_current_round = Mock(return_value=0)  # type: ignore[method-assign]

    with patch("manager.engine.wasabi_engine.sleep"):
        engine.run_engine()

    node.mine_block.assert_called_once_with(WASABI_SETTLEMENT_BLOCKS_AFTER_LIMIT)


def test_split_log_capture_declares_exact_coordinator_sources(tmp_path: Path) -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.SPLIT)

    def download(name: str, _source: str, destination: str) -> None:
        destination_path = Path(destination)
        destination_path.mkdir(parents=True, exist_ok=True)
        if name == "wasabi-coordinator":
            (destination_path / "Logs.txt").write_text("", encoding="utf-8")

    driver.download.side_effect = download

    evidence = engine.store_engine_logs(str(tmp_path))

    assert evidence["complete"] is True
    assert evidence["engine"] == "wasabi"
    assert evidence["sources"] == ["wasabi-coordinator/Logs.txt"]
    assert evidence["positive_count"] == 0


def test_split_log_capture_is_incomplete_when_coordinator_download_fails(tmp_path: Path) -> None:
    engine, driver, _ = configured_engine(BackendArchitecture.SPLIT)

    def download(name: str, _source: str, destination: str) -> None:
        if name == "wasabi-coordinator":
            raise OSError("pod disappeared")
        Path(destination).mkdir(parents=True, exist_ok=True)

    driver.download.side_effect = download

    evidence = engine.store_engine_logs(str(tmp_path))

    assert evidence["complete"] is False
    assert evidence["sources"] == []
    assert "coordinator" in str(evidence["reason"])
