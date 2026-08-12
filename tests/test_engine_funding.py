from typing import cast
from unittest.mock import patch

import pytest

from manager.btc_node import BtcNode
from manager.engine.base.funding import BTC, DISTRIBUTOR_UTXOS, EngineFundingMixin
from manager.engine.base.protocols import EmulatorClient, InvoiceDistributor
from manager.engine.configuration import FundConfig, WalletConfig
from manager.exceptions import CoinjoinEmulatorError


class FundingClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.issued = 0

    def get_new_address(self) -> str:
        self.issued += 1
        return f"{self.name}-address-{self.issued}"


class FundingDistributor:
    def __init__(self, balance: int = 0) -> None:
        self.balance = balance
        self.sent: list[list[tuple[str, int]]] = []
        self.addresses = 0
        self.error: Exception | None = None

    def get_new_address(self) -> str:
        self.addresses += 1
        return f"distributor-address-{self.addresses}"

    def get_balance(self) -> int:
        return self.balance

    def send(self, invoices: object) -> object:
        if self.error is not None:
            raise self.error
        self.sent.append(list(cast(list[tuple[str, int]], invoices)))
        return "ok"


class FundingNode:
    def __init__(self) -> None:
        self.funded: list[tuple[str, int | float]] = []

    def fund_address(self, address: str, amount: int | float) -> None:
        self.funded.append((address, amount))


class FundingHarness(EngineFundingMixin):
    def __init__(self, *clients: FundingClient) -> None:
        self.clients = [cast(EmulatorClient, client) for client in clients]
        self.distributor_impl = FundingDistributor()
        self.distributor = cast(InvoiceDistributor, self.distributor_impl)
        self.node_impl = FundingNode()
        self.node = cast(BtcNode, self.node_impl)
        self.current_block = 0
        self.current_round = 0
        self.invoices: dict[tuple[int, int], list[tuple[str, int]]] = {}


class TestFundDistributor:
    def test_distributor_is_funded_across_many_utxos(self) -> None:
        harness = FundingHarness()
        harness.distributor_impl.balance = 400 * BTC

        harness.fund_distributor(400)

        assert len(harness.node_impl.funded) == DISTRIBUTOR_UTXOS
        assert harness.node_impl.funded[0][1] == 400 / DISTRIBUTOR_UTXOS
        assert {address for address, _ in harness.node_impl.funded} == {
            f"distributor-address-{i + 1}" for i in range(DISTRIBUTOR_UTXOS)
        }

    def test_amounts_below_one_btc_per_utxo_are_not_rounded_away(self) -> None:
        harness = FundingHarness()
        harness.distributor_impl.balance = 10 * BTC

        harness.fund_distributor(10)

        assert sum(amount for _, amount in harness.node_impl.funded) == pytest.approx(
            10,
            abs=1 / BTC,
        )

    def test_funding_waits_until_the_balance_arrives(self) -> None:
        harness = FundingHarness()
        balances = iter([0, 10 * BTC])

        with (
            patch.object(FundingDistributor, "get_balance", side_effect=lambda: next(balances)),
            patch("manager.engine.base.funding.sleep") as sleep,
        ):
            harness.fund_distributor(10)

        assert sleep.call_count == 1

    def test_funding_without_a_node_is_reported(self) -> None:
        harness = FundingHarness()
        harness.node = None

        with pytest.raises(RuntimeError, match="Bitcoin node is not initialized"):
            harness.fund_distributor(10)

    def test_funding_without_a_distributor_is_reported(self) -> None:
        harness = FundingHarness()
        harness.distributor = None

        with pytest.raises(RuntimeError, match="Distributor is not initialized"):
            harness.fund_distributor(10)


class TestPrepareInvoices:
    def test_plain_funds_are_due_immediately(self) -> None:
        client = FundingClient("jcs-000")
        harness = FundingHarness(client)

        harness.prepare_invoices([WalletConfig(funds=[75000, 25000])])

        assert list(harness.invoices) == [(0, 0)]
        assert sorted(harness.invoices[(0, 0)]) == [
            ("jcs-000-address-1", 75000),
            ("jcs-000-address-2", 25000),
        ]

    def test_delayed_funds_are_grouped_by_block_and_round(self) -> None:
        harness = FundingHarness(FundingClient("jcs-000"))

        harness.prepare_invoices(
            [WalletConfig(funds=[FundConfig(value=50000, delay_blocks=5, delay_rounds=2)])]
        )

        assert list(harness.invoices) == [(5, 2)]

    def test_unsupported_fund_entry_is_rejected(self) -> None:
        harness = FundingHarness(FundingClient("jcs-000"))
        wallet = WalletConfig(funds=[1000])
        wallet.funds = [cast(int, "not-a-fund")]

        with pytest.raises(TypeError, match="unsupported fund entry"):
            harness.prepare_invoices([wallet])

    def test_every_client_gets_its_own_addresses(self) -> None:
        first = FundingClient("jcs-000")
        second = FundingClient("jcs-001")
        harness = FundingHarness(first, second)

        harness.prepare_invoices([WalletConfig(funds=[1000]), WalletConfig(funds=[2000])])

        assert sorted(harness.invoices[(0, 0)]) == [
            ("jcs-000-address-1", 1000),
            ("jcs-001-address-1", 2000),
        ]


class TestUpdateInvoicePayments:
    def test_only_the_due_invoices_are_paid(self) -> None:
        harness = FundingHarness()
        harness.current_block = 5
        harness.invoices = {(0, 0): [("early", 1)], (10, 0): [("late", 2)]}

        harness.update_invoice_payments()

        assert harness.distributor_impl.sent == [[("early", 1)]]
        assert list(harness.invoices) == [(10, 0)]

    def test_invoices_waiting_for_a_round_are_kept(self) -> None:
        harness = FundingHarness()
        harness.current_block = 10
        harness.invoices = {(0, 3): [("after-round-3", 1)]}

        harness.update_invoice_payments()

        assert harness.distributor_impl.sent == []
        assert list(harness.invoices) == [(0, 3)]

    def test_failed_payment_remains_scheduled_for_retry(self) -> None:
        harness = FundingHarness()
        harness.invoices = {(0, 0): [("retry-me", 1)]}
        harness.distributor_impl.error = RuntimeError("temporary RPC failure")

        with pytest.raises(CoinjoinEmulatorError, match="Invoice payment failed"):
            harness.update_invoice_payments()

        assert harness.invoices == {(0, 0): [("retry-me", 1)]}


class TestPayInvoices:
    def test_invoices_are_paid_in_batches(self) -> None:
        harness = FundingHarness()

        harness.pay_invoices([(f"address-{i}", 1000) for i in range(7)])

        assert [len(batch) for batch in harness.distributor_impl.sent] == [5, 2]

    def test_payment_failure_is_raised_after_three_attempts(self) -> None:
        harness = FundingHarness()
        harness.distributor_impl.error = Exception("Bad Request")

        with pytest.raises(CoinjoinEmulatorError, match="Invoice payment failed"):
            harness.pay_invoices([("address", 1000)])

    def test_paying_without_a_distributor_is_reported(self) -> None:
        harness = FundingHarness()
        harness.distributor = None

        with pytest.raises(CoinjoinEmulatorError, match="Invoice payment failed"):
            harness.pay_invoices([("address", 1000)])
