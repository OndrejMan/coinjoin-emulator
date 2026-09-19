"""An unreachable Wasabi client must name itself and its container state."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from manager.engine.wasabi_engine import WasabiEngine


def engine(container_state) -> WasabiEngine:
    instance = object.__new__(WasabiEngine)
    instance.args = SimpleNamespace()
    instance.driver = Mock()
    instance.driver.container_state.return_value = container_state
    return instance


def client() -> Mock:
    instance = Mock()
    instance.name = "wasabi-client-003"
    instance.host = "172.19.0.2"
    instance.port = 30746
    instance.start_coinjoin.side_effect = requests.exceptions.ConnectionError(
        "Connection refused"
    )
    return instance


def test_a_dead_client_is_named_together_with_its_pod_phase() -> None:
    """The bare ConnectionError reads as a network fault; it is a dead client."""
    with pytest.raises(RuntimeError) as raised:
        engine("pod phase Succeeded").start_coinjoin(client())

    message = str(raised.value)
    assert "wasabi-client-003" in message
    assert "pod phase Succeeded" in message
    # The reader has to be sent to the client's own log, where the real
    # exception is; nothing else in the run records it.
    assert "own log" in message


def test_an_undiscoverable_container_state_still_names_the_client() -> None:
    """A driver that cannot answer must not replace the error with its own."""
    instance = engine(None)
    instance.driver.container_state.side_effect = RuntimeError("driver is gone")

    with pytest.raises(RuntimeError) as raised:
        instance.start_coinjoin(client())

    message = str(raised.value)
    assert "wasabi-client-003" in message
    assert "container state unknown" in message
    assert "driver is gone" not in message


def test_the_original_error_is_kept_as_the_cause() -> None:
    with pytest.raises(RuntimeError) as raised:
        engine("pod phase Succeeded").start_coinjoin(client())

    assert isinstance(raised.value.__cause__, requests.exceptions.ConnectionError)
