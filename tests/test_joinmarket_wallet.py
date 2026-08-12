from time import time
from unittest.mock import patch

import pytest

from manager.exceptions import RpcError
from manager.wasabi_clients.joinmarket_clients.types import BTC, JsonDict
from manager.wasabi_clients.joinmarket_clients.wallet import JoinMarketWalletMixin


class WalletHarness(JoinMarketWalletMixin):
    def __init__(self, *responses: JsonDict) -> None:
        self.name = "jcs-000"
        self.host = "jcs-000"
        self.port = 28183
        self.walletname = "wallet.jmdat"
        self.seedphrase = ""
        self.has_fidelity_bonds = False
        self._wait_wallet_start = 0.0
        self.token = ""
        self.refresh_token = ""
        self.responses = list(responses)
        self.calls: list[tuple[str, str, JsonDict | None]] = []

    def _rpc(
        self,
        method: str,
        endpoint: str,
        json_data: JsonDict | None = None,
        timeout: int = 60,
        repeat: int = 4,
    ) -> JsonDict:
        self.calls.append((method, endpoint, json_data))
        if not self.responses:
            raise Exception(f"unexpected call: {method} {endpoint}")
        return self.responses.pop(0)


def balance(available: str) -> JsonDict:
    return {"walletinfo": {"available_balance": available}}


class TestCreateWallet:
    def test_wallet_is_created_with_the_default_type_and_password(self) -> None:
        harness = WalletHarness({"token": "t", "refresh_token": "r", "seedphrase": "s"})

        harness._create_wallet()

        assert harness.calls[0][:2] == ("POST", "/wallet/create")
        assert harness.calls[0][2] == {
            "walletname": "wallet.jmdat",
            "password": "password",
            "wallettype": "sw",
        }

    def test_creation_stores_the_tokens_and_the_seedphrase(self) -> None:
        harness = WalletHarness({"token": "t", "refresh_token": "r", "seedphrase": "s"})

        harness._create_wallet()

        assert (harness.token, harness.refresh_token, harness.seedphrase) == ("t", "r", "s")

    def test_fidelity_bond_wallets_are_created_as_sw_fb(self) -> None:
        harness = WalletHarness({"token": "t"})
        harness.has_fidelity_bonds = True

        harness._wait_wallet_create(time() + 1)

        assert harness.calls[0][2] is not None
        assert harness.calls[0][2]["wallettype"] == "sw-fb"


class TestWaitWallet:
    def test_wait_creates_the_wallet_and_then_reads_its_balance(self) -> None:
        harness = WalletHarness({"token": "t"}, balance("0.00000000"))

        assert harness.wait_wallet() is True
        assert [call[1] for call in harness.calls] == [
            "/wallet/create",
            "/wallet/wallet.jmdat/display",
        ]

    def test_wait_reports_failure_when_the_wallet_never_answers(self) -> None:
        harness = WalletHarness()

        assert harness.wait_wallet(timeout=0) is False

    def test_wait_retries_until_the_budget_runs_out(self) -> None:
        harness = WalletHarness({"token": "t"}, balance("0.00000000"))
        harness.responses.insert(0, {})  # the first display attempt answers without a balance

        with patch("manager.wasabi_clients.joinmarket_clients.wallet.sleep") as sleep:
            assert harness.wait_wallet(timeout=5) is True

        assert sleep.call_count == 1


class TestBalance:
    def test_balance_is_returned_in_satoshis(self) -> None:
        harness = WalletHarness(balance("1.50000000"))

        assert harness.get_balance() == int(1.5 * BTC)

    def test_missing_balance_information_is_reported(self) -> None:
        harness = WalletHarness({"walletinfo": {}})

        with pytest.raises(RpcError, match="Could not retrieve available balance"):
            harness.get_balance()


class TestAddressesAndUtxos:
    def test_new_address_is_requested_for_the_given_mixdepth(self) -> None:
        harness = WalletHarness({"address": "bcrt1qfresh"})

        assert harness.get_new_address(mixdepth=3) == "bcrt1qfresh"
        assert harness.calls[0][1] == "/wallet/wallet.jmdat/address/new/3"

    def test_utxos_are_listed_for_the_wallet(self) -> None:
        harness = WalletHarness({"utxos": []})

        assert harness.list_utxos() == {"utxos": []}
        assert harness.calls[0][1] == "/wallet/wallet.jmdat/utxos"
