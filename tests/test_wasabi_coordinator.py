from unittest.mock import patch

import pytest

from manager.wasabi_coordinator import WasabiCoordinator


def test_wait_ready_returns_when_coordinator_responds() -> None:
    coordinator = WasabiCoordinator(host="wasabi-coordinator", port=37128)

    with (
        patch("manager.wasabi_coordinator.monotonic", side_effect=[0, 0]),
        patch("manager.wasabi_coordinator.sleep"),
        patch.object(coordinator, "_get_status", return_value={"rounds": []}),
    ):
        coordinator.wait_ready(timeout=1)


def test_wait_ready_has_bounded_timeout() -> None:
    coordinator = WasabiCoordinator(host="wasabi-coordinator", port=37128)

    with (
        patch("manager.wasabi_coordinator.monotonic", side_effect=[0, 0, 1]),
        patch("manager.wasabi_coordinator.sleep"),
        patch.object(coordinator, "_get_status", return_value=None),
    ):
        with pytest.raises(TimeoutError, match="was not ready after 1s"):
            coordinator.wait_ready(timeout=1)
