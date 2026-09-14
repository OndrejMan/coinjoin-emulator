"""Client startup and health contracts shared by both engines."""

import types
from unittest.mock import Mock, patch

import pytest

from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.engine.engine_base import EngineBase


class StartedClient:
    def __init__(self, idx: int, healthy: bool = True) -> None:
        self.name = f"client-{idx}"
        self.idx = idx
        self.healthy = healthy

    def get_balance(self) -> int:
        if not self.healthy:
            raise RuntimeError("wallet is not responding")
        return 0


class ClientsHarness(EngineBase):
    def __init__(self, failing: set[int] | None = None) -> None:
        super().__init__(types.SimpleNamespace(), None, "/src")
        self.failing = failing or set()
        self.permanently_failing: set[int] = set()
        self.started: list[int] = []
        self.stopped: list[int] = []

    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig("test", 1, 1, "test", [])

    def start_client(self, idx, wallet=None):
        self.started.append(idx)
        if idx in self.failing:
            if idx not in self.permanently_failing:
                self.failing.discard(idx)
            return None
        return StartedClient(idx)

    def stop_client(self, idx):
        self.stopped.append(idx)


def wallet() -> WalletConfig:
    return WalletConfig(funds=[1])


def test_a_failed_client_is_retried_and_kept() -> None:
    harness = ClientsHarness(failing={0})

    with patch("manager.engine.engine_base.sleep"):
        harness.start_clients([wallet(), wallet()])

    assert len(harness.clients) == 2


def test_a_client_that_never_starts_aborts_the_experiment() -> None:
    harness = ClientsHarness(failing={0})
    harness.permanently_failing.add(0)

    with patch("manager.engine.engine_base.sleep"), pytest.raises(
        RuntimeError, match="Failed to start 1 clients after retries"
    ):
        harness.start_clients([wallet(), wallet()])

    assert harness.clients == []


def test_an_unhealthy_client_is_restarted_before_it_is_accepted() -> None:
    harness = ClientsHarness()
    unhealthy = StartedClient(0, healthy=False)
    harness.start_client = Mock(side_effect=[unhealthy, StartedClient(0)])  # type: ignore[method-assign]

    with patch("manager.engine.engine_base.sleep"):
        harness.start_clients([wallet()])

    assert harness.clients[0].healthy is True


def test_validate_clients_requires_one_client_per_scenario_wallet() -> None:
    harness = ClientsHarness()
    harness.scenario.wallets = [wallet(), wallet()]
    harness.clients = [StartedClient(0)]

    with pytest.raises(RuntimeError, match="Expected 2 clients, but only 1 started"):
        harness.validate_clients()


def test_validate_clients_rejects_an_unhealthy_client() -> None:
    harness = ClientsHarness()
    harness.scenario.wallets = [wallet()]
    harness.clients = [StartedClient(0, healthy=False)]

    with pytest.raises(RuntimeError, match="client-0 .wallet is not responding"):
        harness.validate_clients()


def test_funding_retry_does_not_repeat_successful_batches() -> None:
    harness = ClientsHarness()
    invoices = [(f"address-{i}", 1000) for i in range(6)]
    harness.invoices = {(0, 0): invoices.copy()}
    harness.distributor = Mock()
    harness.distributor.send.side_effect = ["txid-1", *[RuntimeError("RPC failed") for _ in range(3)], "txid-2"]

    with pytest.raises(Exception, match="Invoice payment failed"):
        harness.update_invoice_payments()

    assert harness.invoices == {(0, 0): invoices[5:]}
    harness.update_invoice_payments()

    assert harness.invoices == {}
    assert harness.distributor.send.call_args_list[0].args == (invoices[:5],)
    assert all(call.args == (invoices[5:],) for call in harness.distributor.send.call_args_list[1:])
