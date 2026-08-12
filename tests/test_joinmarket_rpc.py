import asyncio
from unittest.mock import Mock, patch

import httpx
import pytest

from manager.wasabi_clients.joinmarket_clients.rpc import JoinMarketRpcMixin
from manager.wasabi_clients.joinmarket_clients.types import JoinmarketConflictException, JsonDict


class RpcHarness(JoinMarketRpcMixin):
    def __init__(self, token: str = "") -> None:
        self.host = "jcs-000"
        self.port = 28183
        self.proxy = ""
        self.walletname = "wallet.jmdat"
        self.token = token
        self.refresh_token = ""
        self._async_client: httpx.AsyncClient | None = None
        self._unlock_lock: asyncio.Lock | None = None
        self.coin_history_updates = 0

    def update_coin_history(self) -> None:
        self.coin_history_updates += 1

    async def update_coin_history_async(self) -> None:
        self.coin_history_updates += 1


def response(status_code: int = 200, payload: JsonDict | None = None, text: str = "") -> Mock:
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.json.return_value = payload if payload is not None else {}
    return mock_response


class TestRpc:
    def test_request_targets_the_jmwalletd_api(self) -> None:
        harness = RpcHarness()

        with patch(
            "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
            return_value=response(payload={"session": True}),
        ) as request:
            assert harness._rpc("GET", "/session") == {"session": True}

        assert request.call_args.kwargs["url"] == "https://jcs-000:28183/api/v1/session"
        assert request.call_args.kwargs["method"] == "GET"

    def test_stored_token_is_sent_as_a_bearer_header(self) -> None:
        harness = RpcHarness(token="jm-token")

        with patch(
            "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
            return_value=response(),
        ) as request:
            harness._rpc("GET", "/session")

        assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer jm-token"

    def test_proxy_is_used_for_https_when_configured(self) -> None:
        harness = RpcHarness()
        harness.proxy = "http://proxy:8080"

        with patch(
            "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
            return_value=response(),
        ) as request:
            harness._rpc("GET", "/session")

        assert request.call_args.kwargs["proxies"] == {"https": "http://proxy:8080"}

    def test_unauthorized_response_unlocks_the_wallet_and_retries(self) -> None:
        harness = RpcHarness()

        with (
            patch(
                "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
                side_effect=[
                    response(status_code=401),
                    response(payload={"walletname": "wallet.jmdat"}),
                ],
            ) as request,
            patch.object(RpcHarness, "unlock_wallet", autospec=True) as unlock,
        ):
            assert harness._rpc("GET", "/session") == {"walletname": "wallet.jmdat"}

        assert unlock.call_count == 1
        assert request.call_count == 2

    def test_conflict_response_raises_the_joinmarket_conflict(self) -> None:
        harness = RpcHarness()

        with (
            patch(
                "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
                return_value=response(status_code=409, text="coinjoin in progress"),
            ),
            patch("manager.wasabi_clients.joinmarket_clients.rpc.sleep"),
            pytest.raises(JoinmarketConflictException, match="coinjoin in progress"),
        ):
            harness._rpc("POST", "/wallet/wallet.jmdat/taker/coinjoin")

    def test_server_error_is_retried_until_the_budget_is_spent(self) -> None:
        harness = RpcHarness()

        with (
            patch(
                "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
                return_value=response(status_code=500, payload={"message": "boom"}),
            ) as request,
            patch("manager.wasabi_clients.joinmarket_clients.rpc.sleep"),
            pytest.raises(Exception, match="Error 500: boom"),
        ):
            harness._rpc("GET", "/session", repeat=3)

        assert request.call_count == 3


class TestSession:
    def test_failing_session_is_reported_as_empty(self) -> None:
        harness = RpcHarness()

        with (
            patch(
                "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
                side_effect=OSError("connection refused"),
            ),
            patch("manager.wasabi_clients.joinmarket_clients.rpc.sleep"),
        ):
            assert harness.session() == {}

    def test_status_update_refreshes_the_coin_history_first(self) -> None:
        harness = RpcHarness()

        with patch(
            "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
            return_value=response(payload={"session": True}),
        ):
            assert harness.update_status() == {"session": True}

        assert harness.coin_history_updates == 1


class TestUnlockWallet:
    def test_unlock_stores_both_tokens(self) -> None:
        harness = RpcHarness()

        with patch(
            "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
            return_value=response(payload={"token": "new-token", "refresh_token": "new-refresh"}),
        ) as request:
            harness.unlock_wallet()

        assert request.call_args.kwargs["url"].endswith("/wallet/wallet.jmdat/unlock")
        assert harness.token == "new-token"
        assert harness.refresh_token == "new-refresh"

    def test_unlock_sends_the_default_password(self) -> None:
        harness = RpcHarness()

        with patch(
            "manager.wasabi_clients.joinmarket_clients.rpc.requests.request",
            return_value=response(payload={"token": "new-token"}),
        ) as request:
            harness.unlock_wallet()

        assert request.call_args.kwargs["json"] == {"password": "password"}
