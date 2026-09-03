"""Readiness waits must give up instead of hanging a run forever."""

from unittest.mock import Mock, patch

import pytest

from manager.wasabi_backend import WasabiBackend
from manager.wasabi_clients.wasabi_client_base import WasabiClientBase


def test_the_backend_readiness_wait_has_a_deadline() -> None:
    backend = WasabiBackend(host="wasabi-backend", port=37127)
    backend._get_status = Mock(side_effect=RuntimeError("connection refused"))  # pylint: disable=protected-access

    with patch("manager.wasabi_backend.monotonic", side_effect=[0.0, 200.0]):
        with pytest.raises(TimeoutError, match="was not ready after 120s"):
            backend.wait_ready()


def test_a_ready_backend_returns_immediately() -> None:
    backend = WasabiBackend(host="wasabi-backend", port=37127)
    backend._get_status = Mock(return_value={})  # pylint: disable=protected-access

    with patch("manager.wasabi_backend.monotonic", side_effect=[0.0, 1.0]):
        backend.wait_ready()


def test_the_client_readiness_wait_has_a_deadline() -> None:
    client = object.__new__(WasabiClientBase)
    client.host = "wasabi-client-000"
    client.port = 37128
    client.get_status = Mock(side_effect=RuntimeError("connection refused"))

    with patch("manager.wasabi_clients.wasabi_client_base.monotonic", side_effect=[0.0, 200.0]):
        with pytest.raises(TimeoutError, match="was not ready after 60s"):
            client.wait_ready(timeout=60)
