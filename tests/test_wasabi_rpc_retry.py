"""Retry behaviour of the Wasabi client RPC."""

from unittest.mock import Mock, patch

import pytest
import requests

from manager.wasabi_clients.wasabi_client_base import WasabiClientBase


def client() -> WasabiClientBase:
    return WasabiClientBase(name="wasabi-client-distributor", host="host", port=37131)


def ok(body):
    result = Mock()
    result.json.return_value = body
    return result


def test_a_new_address_survives_one_connect_timeout() -> None:
    """fund_distributor asks 200 times in a row; one blip must not end the run."""
    answers = [
        requests.exceptions.ConnectTimeout("connect timed out"),
        ok({"result": {"address": "bcrt1qexample"}}),
    ]
    with patch("manager.wasabi_clients.wasabi_client_base.requests.post", side_effect=answers), \
         patch("manager.wasabi_clients.wasabi_client_base.sleep") as slept:
        assert client().get_new_address() == "bcrt1qexample"

    slept.assert_called_once()


def test_retries_are_spread_out_but_not_after_the_last_attempt() -> None:
    """Immediate retries land in the same stall, and a trailing sleep is waste."""
    timeout = requests.exceptions.ConnectTimeout("connect timed out")
    with patch(
        "manager.wasabi_clients.wasabi_client_base.requests.post",
        side_effect=[timeout, timeout, timeout],
    ), patch("manager.wasabi_clients.wasabi_client_base.sleep") as slept:
        with pytest.raises(requests.exceptions.ConnectTimeout):
            client().get_new_address()

    assert slept.call_count == 2


def test_an_rpc_error_is_not_retried() -> None:
    """Only timeouts are transient; a refusal from the wallet is an answer."""
    with patch(
        "manager.wasabi_clients.wasabi_client_base.requests.post",
        return_value=ok({"error": "no such wallet"}),
    ) as post:
        with pytest.raises(Exception):
            client().get_new_address()

    assert post.call_count == 1
