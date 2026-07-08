from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

from manager.btc_node import BtcNode
from manager.engine.configuration import WalletConfig
from manager.engine.wasabi_engine import (
    WASABI_CLIENT_START_TIMEOUT_SECONDS,
    WASABI_COORDINATOR_START_TIMEOUT_SECONDS,
    WASABI_SETTLEMENT_BLOCKS_AFTER_LIMIT,
    WasabiEngine,
)
from manager.exceptions import StartupError
from manager.wasabi_backend_factory import BackendArchitecture


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
    engine.node = cast(BtcNode, SimpleNamespace(internal_ip="10.42.0.2"))
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


def test_coordinator_timeout_includes_container_logs() -> None:
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

    coordinator.wait_ready.assert_called_once_with(
        timeout=WASABI_COORDINATOR_START_TIMEOUT_SECONDS
    )
    driver.logs.assert_called_once_with("wasabi-coordinator")
    assert WASABI_COORDINATOR_START_TIMEOUT_SECONDS == 120


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
