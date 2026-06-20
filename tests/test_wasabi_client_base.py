from unittest.mock import Mock, patch

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from manager.wasabi_clients.wasabi_client_base import WasabiClientBase


def response(address: str = "bcrt1qtest") -> Mock:
    mock_response = Mock()
    mock_response.json.return_value = {"result": {"address": address}}
    return mock_response


def test_get_new_address_retries_connection_reset() -> None:
    client = WasabiClientBase()

    with (
        patch(
            "manager.wasabi_clients.wasabi_client_base.requests.post",
            side_effect=[RequestsConnectionError("connection reset"), response()],
        ) as post,
        patch("manager.wasabi_clients.wasabi_client_base.sleep"),
    ):
        assert client.get_new_address() == "bcrt1qtest"

    assert post.call_count == 2


def test_get_new_address_reraises_after_retry_budget_is_exhausted() -> None:
    client = WasabiClientBase()

    with (
        patch(
            "manager.wasabi_clients.wasabi_client_base.requests.post",
            side_effect=RequestsConnectionError("connection reset"),
        ) as post,
        patch("manager.wasabi_clients.wasabi_client_base.sleep"),
        pytest.raises(RequestsConnectionError, match="connection reset"),
    ):
        client.get_new_address()

    assert post.call_count == 30
