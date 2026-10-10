"""Coordinator readiness distinguishes an empty response from a failed request."""

from unittest.mock import patch

import pytest

from manager.wasabi_coordinator import WasabiCoordinator


@pytest.mark.parametrize("status", [{}, [], {"rounds": []}])
def test_empty_successful_responses_are_ready(status) -> None:
    coordinator = WasabiCoordinator()
    with (
        patch.object(coordinator, "_get_status", return_value=status) as get_status,
        patch("manager.wasabi_coordinator.monotonic", side_effect=[0, 0, 2]),
        patch("manager.wasabi_coordinator.sleep") as sleep,
    ):
        coordinator.wait_ready(timeout=1)

    get_status.assert_called_once_with()
    sleep.assert_not_called()


def test_failed_requests_still_time_out() -> None:
    coordinator = WasabiCoordinator()
    with (
        patch.object(coordinator, "_get_status", return_value=None),
        patch("manager.wasabi_coordinator.monotonic", side_effect=[0, 0, 2]),
        patch("manager.wasabi_coordinator.sleep"),
        pytest.raises(TimeoutError, match="was not ready"),
    ):
        coordinator.wait_ready(timeout=1)
