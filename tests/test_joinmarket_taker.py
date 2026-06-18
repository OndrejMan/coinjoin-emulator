import unittest
from unittest.mock import patch

from manager.wasabi_clients.joinmarket_client import JoinMarketClientServer


class JoinMarketTakerTest(unittest.TestCase):
    def test_start_coinjoin_posts_taker_payload(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch.object(client, "_rpc", return_value={"accepted": True}) as rpc:
            result = client.start_coinjoin(
                mixdepth=0,
                amount_sats=100_000,
                counterparties=3,
                destination="bcrt1destination",
                txfee=5000,
            )

        self.assertEqual(result, {"accepted": True})
        rpc.assert_called_once_with(
            "POST",
            "/wallet/wallet/taker/coinjoin",
            json_data={
                "mixdepth": 0,
                "amount_sats": 100_000,
                "counterparties": 3,
                "destination": "bcrt1destination",
                "txfee": 5000,
            },
        )

    def test_send_raises_when_direct_send_times_out(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch.object(
            client,
            "simple_send",
            side_effect=TimeoutError("Failed to send funds, attempt timed out."),
        ):
            with self.assertRaisesRegex(TimeoutError, "Failed to send funds"):
                client.send([("bcrt1destination", 100000)])

    def test_simple_send_raises_timeout_when_retries_expire(self) -> None:
        client = JoinMarketClientServer(host="dind")

        with patch("manager.wasabi_clients.joinmarket.taker.time", side_effect=[0, 31]):
            with self.assertRaisesRegex(TimeoutError, "Failed to send funds"):
                client.simple_send(destination_address="bcrt1destination", amount_sats=100000)
