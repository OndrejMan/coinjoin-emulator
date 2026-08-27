from types import SimpleNamespace

import pytest

from manager.btc_node import BtcNode
from manager.engine.configuration import ScenarioConfig
from manager.engine.joinmarket.runner import JoinMarketRunnerMixin


class RunnerHarness(JoinMarketRunnerMixin):
    def __init__(self) -> None:
        self.node: BtcNode | None = None
        self.scenario = ScenarioConfig(
            name="runner",
            rounds=1,
            blocks=0,
            default_version="joinmarket",
            wallets=[],
        )
        self.clients = []
        self.current_block = 0
        self.current_round = 0

    def update_invoice_payments(self) -> None:
        raise AssertionError("run_engine should fail before updating invoices")

    def update_coinjoins_joinmarket(self) -> None:
        raise AssertionError("run_engine should fail before updating coinjoins")

    def completion_block_limit(self) -> int:
        return self._joinmarket_completion_block_limit()


class TestJoinMarketRunner:
    def test_requires_initialized_bitcoin_node(self) -> None:
        runner = RunnerHarness()

        with pytest.raises(RuntimeError, match="Bitcoin node is not initialized"):
            runner.run_engine()

    def test_completion_block_limit_includes_retry_attempt_budget(self) -> None:
        runner = RunnerHarness()
        runner.clients = [
            SimpleNamespace(type="taker"),
            SimpleNamespace(type="taker"),
            SimpleNamespace(type="maker"),
        ]

        assert runner.completion_block_limit() == 580
