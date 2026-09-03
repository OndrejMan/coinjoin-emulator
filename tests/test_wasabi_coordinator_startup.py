from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

from manager.btc_node import BtcNode
from manager.driver import Driver
from manager.engine.wasabi_engine import WasabiEngine, coordinator_retry_reason
from manager.exceptions import StartupError
from manager.wasabi_backend_factory import BackendArchitecture


def engine() -> WasabiEngine:
    instance = object.__new__(WasabiEngine)
    instance.driver = cast(Driver, Mock())
    instance.args = SimpleNamespace(
        image_prefix="registry/",
        btc_node_ip="",
        proxy="",
        in_cluster=False,
        control_ip="localhost",
    )
    instance.node = cast(BtcNode, SimpleNamespace(internal_ip="btc-node"))
    instance.backend_architecture = BackendArchitecture.SPLIT
    return instance


@pytest.mark.parametrize(
    ("logs", "reason"),
    [
        ("Bitcoin Node is not fully synchronized", "raced a freshly mined block"),
        ("Failed to bind: address already in use", "could not bind port 37128"),
    ],
)
def test_retry_reason_recognizes_transient_failures(logs: str, reason: str) -> None:
    assert coordinator_retry_reason(logs) == reason


def test_transient_coordinator_failure_is_restarted() -> None:
    instance = engine()
    driver = cast(Mock, instance.driver)
    driver.run.return_value = ("coordinator", {37128: 37128}, None)
    driver.logs.return_value = "Failed to bind: address already in use"
    first = Mock()
    first.wait_ready.side_effect = TimeoutError("not ready")
    second = Mock()

    with (
        patch("manager.engine.wasabi_engine.create_coordinator", side_effect=[first, second]),
        patch("manager.engine.wasabi_engine.sleep"),
    ):
        instance.start_wasabi_coordinator()

    assert driver.run.call_count == 2
    driver.stop.assert_called_once_with("wasabi-coordinator")
    second.wait_ready.assert_called_once_with(timeout=120)


def test_unknown_coordinator_failure_is_not_retried() -> None:
    instance = engine()
    driver = cast(Mock, instance.driver)
    driver.run.return_value = ("coordinator", {37128: 37128}, None)
    driver.logs.return_value = "fatal configuration error"
    coordinator = Mock()
    coordinator.wait_ready.side_effect = TimeoutError("not ready")

    with (
        patch("manager.engine.wasabi_engine.create_coordinator", return_value=coordinator),
        patch("manager.engine.wasabi_engine.sleep"),
    ):
        with pytest.raises(StartupError, match="fatal configuration error"):
            instance.start_wasabi_coordinator()

    driver.stop.assert_not_called()
    driver.run.assert_called_once()
