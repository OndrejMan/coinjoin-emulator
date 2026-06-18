import unittest
from unittest.mock import patch

from manager.wasabi_clients.joinmarket_client import JoinMarketClientServer
from tests.joinmarket_helpers import response


class JoinMarketMakerTest(unittest.TestCase):
    def test_start_maker_returns_conflict_response(self) -> None:
        client = JoinMarketClientServer(host="dind")
        client.token = "token"
        conflict_response = response(status_code=409, text="wallet has no confirmed coins")

        with patch(
            "manager.wasabi_clients.joinmarket.rpc.requests.request",
            return_value=conflict_response,
        ):
            result = client.start_maker(
                txfee=0,
                cjfee_a=5000,
                cjfee_r=0.00004,
                ordertype="reloffer",
                minsize=27300,
            )

        self.assertIs(result, conflict_response)
