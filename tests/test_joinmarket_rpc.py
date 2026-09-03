"""jmwalletd transport contracts."""

from unittest.mock import Mock, patch

import pytest

from manager.exceptions import RpcError
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer


def client() -> JoinMarketClientServer:
    instance = object.__new__(JoinMarketClientServer)
    instance.host = "jcs-000"
    instance.port = 28183
    instance.proxy = None
    instance.token = "token"
    instance.unlock_wallet = Mock()
    return instance


def unauthorized() -> Mock:
    response = Mock()
    response.status_code = 401
    response.text = "Unauthorized"
    return response


def test_a_wallet_that_never_unlocks_fails_instead_of_returning_the_401_body() -> None:
    instance = client()

    with patch(
        "manager.wasabi_clients.joinmarket_clients.joinmarket_client_base.requests.request",
        return_value=unauthorized(),
    ):
        with patch("manager.wasabi_clients.joinmarket_clients.joinmarket_client_base.sleep"):
            with pytest.raises(RpcError, match="stayed unauthorized after 2 attempts"):
                instance._rpc("GET", "/wallet/all", repeat=2)  # pylint: disable=protected-access

    assert instance.unlock_wallet.call_count == 2
