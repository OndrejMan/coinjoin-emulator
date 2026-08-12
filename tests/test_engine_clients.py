import multiprocessing.pool
from typing import cast
from unittest.mock import Mock, patch

import pytest

from manager.engine.base.clients import EngineClientsMixin
from manager.engine.base.protocols import EmulatorClient
from manager.engine.configuration import JoinMarketConfig, ScenarioConfig, WalletConfig


class StartedClient:
    def __init__(self, idx: int) -> None:
        self.name = f"client-{idx}"
        self.idx = idx

    def wait_wallet(self, timeout: int | None = None) -> bool:
        return True

    def get_balance(self) -> int:
        return 0


class ClientsHarness(EngineClientsMixin):
    def __init__(self, failing: set[int] | None = None) -> None:
        self.clients: list[EmulatorClient] = []
        self.scenario = ScenarioConfig(
            name="test", rounds=0, blocks=0, default_version="joinmarket", wallets=[]
        )
        self.failing = failing or set()
        self.permanently_failing: set[int] = set()
        self.started: list[int] = []
        self.stopped: list[int] = []

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> EmulatorClient | None:
        self.started.append(idx)
        if idx in self.failing:
            return None
        return cast(EmulatorClient, StartedClient(idx))

    def stop_client(self, idx: int) -> None:
        self.stopped.append(idx)
        if idx not in self.permanently_failing:
            self.failing.discard(idx)


def wallet() -> WalletConfig:
    return WalletConfig(funds=[1000])


def bond_wallet() -> WalletConfig:
    return WalletConfig(funds=[1000], joinmarket=JoinMarketConfig(fidelity_bond={"enabled": True}))


class TestStartClients:
    def test_every_wallet_gets_a_client_in_scenario_order(self) -> None:
        harness = ClientsHarness()

        harness.start_clients([wallet(), wallet(), wallet()])

        assert [cast(StartedClient, client).idx for client in harness.clients] == [0, 1, 2]

    def test_clients_are_appended_to_the_ones_already_running(self) -> None:
        harness = ClientsHarness()
        harness.start_clients([wallet()])

        harness.start_clients([wallet()])

        assert [cast(StartedClient, client).idx for client in harness.clients] == [0, 1]

    def test_failed_client_is_stopped_and_started_again(self) -> None:
        harness = ClientsHarness(failing={1})

        with patch("manager.engine.base.clients.sleep"):
            harness.start_clients([wallet(), wallet()])

        assert harness.stopped == [1]
        assert harness.started == [0, 1, 1]
        assert len(harness.clients) == 2

    def test_client_that_never_starts_aborts_the_experiment(self) -> None:
        harness = ClientsHarness(failing={0})
        harness.permanently_failing.add(0)

        with patch("manager.engine.base.clients.sleep"), pytest.raises(
            RuntimeError, match="Failed to start 1 clients after retries"
        ):
            harness.start_clients([wallet(), wallet()])

        assert harness.clients == []
        assert harness.stopped == [0, 0, 0]


class TestValidateClients:
    def test_requires_one_client_per_scenario_wallet(self) -> None:
        harness = ClientsHarness()
        harness.scenario.wallets = [wallet(), wallet()]
        harness.clients = [cast(EmulatorClient, StartedClient(0))]

        with pytest.raises(RuntimeError, match="Expected 2 clients, but only 1 started"):
            harness.validate_clients()

    def test_rejects_an_unhealthy_client(self) -> None:
        harness = ClientsHarness()
        harness.scenario.wallets = [wallet()]
        client = Mock(name="client")
        client.name = "client-0"
        client.get_balance.side_effect = OSError("wallet RPC unavailable")
        harness.clients = [cast(EmulatorClient, client)]

        with pytest.raises(RuntimeError, match="client-0.*wallet RPC unavailable"):
            harness.validate_clients()

        client.get_balance.assert_called_once_with()
        client.wait_wallet.assert_not_called()

    def test_healthcheck_does_not_restart_an_existing_wallet(self) -> None:
        harness = ClientsHarness()
        harness.scenario.wallets = [wallet()]
        client = Mock(name="client")
        client.name = "client-0"
        client.get_balance.return_value = 0
        harness.clients = [cast(EmulatorClient, client)]

        harness.validate_clients()

        client.get_balance.assert_called_once_with()
        client.wait_wallet.assert_not_called()


class TestStartClassifiedWallets:
    def test_regular_wallets_are_started_in_one_go(self) -> None:
        harness = ClientsHarness()

        with multiprocessing.pool.ThreadPool(2) as pool:
            results = harness._start_classified_wallets(pool, [(0, wallet()), (1, wallet())])

        assert sorted(results) == [0, 1]
        assert harness.started == [0, 1]

    def test_fidelity_bond_wallets_are_started_in_batches(self) -> None:
        harness = ClientsHarness()
        wallet_list = [(idx, bond_wallet()) for idx in range(3)]

        with multiprocessing.pool.ThreadPool(2) as pool:
            with patch("manager.engine.base.clients.sleep") as sleep:
                results = harness._start_classified_wallets(
                    pool, wallet_list, fb_batch_size=2, fb_batch_delay=15
                )

        assert sorted(results) == [0, 1, 2]
        assert sleep.call_args_list[0].args == (15,)
        assert sleep.call_count == 1

    def test_failed_startup_is_reported_as_a_missing_client(self) -> None:
        harness = ClientsHarness(failing={1})

        with multiprocessing.pool.ThreadPool(2) as pool:
            results = harness._start_classified_wallets(pool, [(0, wallet()), (1, wallet())])

        assert results[1] is None
        assert results[0] is not None
