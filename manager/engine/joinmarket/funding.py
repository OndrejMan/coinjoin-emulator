from ...btc_node import BtcNode
from ..engine_base import BTC


class JoinMarketFundingMixin:
    node: BtcNode | None
    current_block: int
    current_round: int

    def pay_invoices(self, addressed_invoices: list[tuple[str, int]]) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")

        print(
            f"- funding {len(addressed_invoices)} JoinMarket invoices directly "
            f"(block {self.current_block}, round {self.current_round})"
        )
        for address, amount_sats in addressed_invoices:
            self.node.fund_address(address, amount_sats / BTC)
            print(f"- funded {amount_sats} sats to {address}")

        if addressed_invoices:
            self.node.mine_block()
            print("- confirmed JoinMarket invoice funding")
