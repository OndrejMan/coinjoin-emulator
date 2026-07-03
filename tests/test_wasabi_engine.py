from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from manager.btc_node import BtcNode
from manager.engine.wasabi_engine import WasabiEngine
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
