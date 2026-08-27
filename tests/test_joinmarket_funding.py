from typing import cast

from manager.btc_node import BtcNode
from manager.engine.joinmarket.funding import JoinMarketFundingMixin


class FundingNode:
    def __init__(self) -> None:
        self.fund_address_calls: list[tuple[str, float]] = []
        self.mine_block_calls: list[int] = []

    def fund_address(self, address: str, amount: float) -> None:
        self.fund_address_calls.append((address, amount))

    def mine_block(self, count: int = 1) -> bool:
        self.mine_block_calls.append(count)
        return True


class FundingHarness(JoinMarketFundingMixin):
    def __init__(self, node: FundingNode | None) -> None:
        self.node = cast(BtcNode | None, node)
        self.current_block = 12
        self.current_round = 3


class TestJoinMarketFunding:
    def test_pays_joinmarket_invoices_directly_from_node(self) -> None:
        node = FundingNode()
        harness = FundingHarness(node)

        harness.pay_invoices([("bcrt1maker", 100_000_000), ("bcrt1taker", 20_000_000)])

        assert node.fund_address_calls == [("bcrt1maker", 1.0), ("bcrt1taker", 0.2)]
        assert node.mine_block_calls == [1]

    def test_does_not_mine_for_empty_invoice_batch(self) -> None:
        node = FundingNode()
        harness = FundingHarness(node)

        harness.pay_invoices([])

        assert not node.fund_address_calls
        assert not node.mine_block_calls
