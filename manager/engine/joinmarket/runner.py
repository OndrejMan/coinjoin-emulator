import sys
from time import sleep
from typing import TYPE_CHECKING

from ...btc_node import BtcNode
from ...exceptions import CoinjoinEmulatorError
from ..configuration import ScenarioConfig
from .constants import (
    JOINMARKET_FINAL_SETTLE_BLOCKS,
    JOINMARKET_LOOP_SLEEP_SECONDS,
    JOINMARKET_ROUND_TIMEOUT_BLOCKS,
)


class JoinMarketRunnerMixin:
    node: BtcNode | None
    scenario: ScenarioConfig
    current_block: int
    current_round: int

    if TYPE_CHECKING:
        def update_invoice_payments(self) -> None: ...
        def update_coinjoins_joinmarket(self) -> None: ...

    def run_engine(self) -> None:
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")

        self.update_invoice_payments()
        initial_block = self.node.get_block_count()
        for _ in range(5):
            self.node.mine_block()

        while (self.scenario.rounds == 0 or self.current_round < self.scenario.rounds) and (
            self.scenario.blocks == 0 or self.current_block < self.scenario.blocks
        ):
            if (
                self.scenario.blocks == 0
                and self.scenario.rounds > 0
                and self.current_block > (self.scenario.rounds * JOINMARKET_ROUND_TIMEOUT_BLOCKS) + 10
            ):
                raise RuntimeError(
                    f"JoinMarket scenario did not complete {self.scenario.rounds} "
                    f"round(s) within {self.current_block} simulated blocks"
                )

            for _ in range(3):
                try:
                    self.current_block = self.node.get_block_count() - initial_block
                    break
                except (CoinjoinEmulatorError, RuntimeError, OSError) as e:
                    print("- could not get blocks".ljust(60), end="\r")
                    print(f"Block exception: {e}", file=sys.stderr)

            self.update_invoice_payments()
            self.update_coinjoins_joinmarket()

            print(
                f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60),
                end="\r",
            )
            if self.scenario.blocks == 0 or self.current_block < self.scenario.blocks:
                self.node.mine_block()
            sleep(JOINMARKET_LOOP_SLEEP_SECONDS)

        print()
        print("- limit reached")
        self.node.mine_block(JOINMARKET_FINAL_SETTLE_BLOCKS)
