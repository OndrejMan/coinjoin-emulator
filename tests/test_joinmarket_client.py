import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from manager.wasabi_clients.joinmarket_client import JoinMarketClientServer


def response(status_code=200, body=None, text=""):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = body or {}
    mock_response.text = text
    return mock_response


class JoinMarketClientServerTest(unittest.TestCase):
    def test_protected_rpc_unlocks_before_request_when_token_is_missing(self):
        client = JoinMarketClientServer(host="dind")
        unlock_response = response(body={"token": "new-token", "refresh_token": "refresh"})
        display_response = response(body={"walletinfo": {"available_balance": "1.00000000"}})

        with patch(
            "manager.wasabi_clients.joinmarket_client.requests.request",
            side_effect=[unlock_response, display_response],
        ) as request:
            result = client._rpc("GET", "/wallet/wallet/display")

        self.assertEqual(result, {"walletinfo": {"available_balance": "1.00000000"}})
        self.assertEqual(client.token, "new-token")
        self.assertEqual(
            request.call_args_list[0].kwargs["url"],
            "https://dind:28183/api/v1/wallet/wallet/unlock",
        )
        self.assertEqual(request.call_args_list[0].kwargs["headers"], {})
        self.assertEqual(
            request.call_args_list[1].kwargs["headers"],
            {"Authorization": "Bearer new-token"},
        )

    def test_create_wallet_and_unlock_do_not_require_existing_token(self):
        client = JoinMarketClientServer(host="dind")
        create_response = response(body={"token": "created-token", "refresh_token": "created-refresh"})
        unlock_response = response(body={"token": "unlocked-token", "refresh_token": "unlocked-refresh"})

        with patch(
            "manager.wasabi_clients.joinmarket_client.requests.request",
            side_effect=[create_response, unlock_response],
        ) as request:
            client._create_wallet()
            client.unlock_wallet()

        self.assertEqual(request.call_args_list[0].kwargs["headers"], {})
        self.assertEqual(request.call_args_list[1].kwargs["headers"], {})
        self.assertEqual(client.token, "unlocked-token")
        self.assertEqual(client.refresh_token, "unlocked-refresh")

    def test_protected_rpc_refreshes_token_once_after_401(self):
        client = JoinMarketClientServer(host="dind")
        client.token = "expired-token"
        unauthorized_response = response(status_code=401, body={"message": "expired"}, text="expired")
        unlock_response = response(body={"token": "fresh-token", "refresh_token": "fresh-refresh"})
        display_response = response(body={"walletinfo": {"available_balance": "0.50000000"}})

        with patch(
            "manager.wasabi_clients.joinmarket_client.requests.request",
            side_effect=[unauthorized_response, unlock_response, display_response],
        ) as request:
            result = client._rpc("GET", "/wallet/wallet/display")

        self.assertEqual(result, {"walletinfo": {"available_balance": "0.50000000"}})
        self.assertEqual(
            request.call_args_list[0].kwargs["headers"],
            {"Authorization": "Bearer expired-token"},
        )
        self.assertEqual(request.call_args_list[1].kwargs["headers"], {})
        self.assertEqual(
            request.call_args_list[2].kwargs["headers"],
            {"Authorization": "Bearer fresh-token"},
        )

    def test_protected_rpc_does_not_continue_when_unlock_fails(self):
        client = JoinMarketClientServer(host="dind")
        unlock_response = response(status_code=401, body={"message": "unauthorized"}, text="unauthorized")

        with patch(
            "manager.wasabi_clients.joinmarket_client.requests.request",
            return_value=unlock_response,
        ) as request:
            with self.assertRaisesRegex(Exception, "Error 401: unauthorized"):
                client._rpc("GET", "/wallet/wallet/display")

        self.assertEqual(request.call_count, 1)
        self.assertEqual(
            request.call_args.kwargs["url"],
            "https://dind:28183/api/v1/wallet/wallet/unlock",
        )
        self.assertEqual(request.call_args.kwargs["headers"], {})


if __name__ == "__main__":
    unittest.main()
