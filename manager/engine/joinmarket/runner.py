from time import sleep
from typing import TYPE_CHECKING

from manager import log_output as log

from ...btc_node import BtcNode
from ...exceptions import CoinjoinEmulatorError
from ..configuration import ScenarioConfig
from ..engine_base import EmulatorClient
from .constants import (
    JOINMARKET_FINAL_SETTLE_BLOCKS,
    JOINMARKET_LOOP_SLEEP_SECONDS,
    JOINMARKET_ROUND_TIMEOUT_BLOCKS,
    JOINMARKET_TAKER_MAX_ATTEMPTS,
    JOINMARKET_TAKER_RETRY_COOLDOWN_BLOCKS,
)


class JoinMarketRunnerMixin:
    node: BtcNode | None
    clients: list[EmulatorClient]
    scenario: ScenarioConfig
    current_block: int
    current_round: int

    if TYPE_CHECKING:
        def update_invoice_payments(self) -> None: ...
        def update_coinjoins_joinmarket(self) -> None: ...

    def _joinmarket_completion_block_limit(self) -> int:
        taker_count = len([
            client for client in self.clients
            if client.type == "taker"
        ]) or 1
        retry_attempt_blocks = (
            JOINMARKET_ROUND_TIMEOUT_BLOCKS
            + JOINMARKET_TAKER_RETRY_COOLDOWN_BLOCKS
        )
        return (
            self.scenario.rounds
            * taker_count
            * JOINMARKET_TAKER_MAX_ATTEMPTS
            * retry_attempt_blocks
            + 10
        )

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
            for _ in range(3):
                try:
                    self.current_block = self.node.get_block_count() - initial_block
                    break
                except (CoinjoinEmulatorError, RuntimeError, OSError) as e:
                    log.warning("- could not get blocks".ljust(60), end="\r")
                    log.error(f"Block exception: {e}")

            if (
                self.scenario.blocks == 0
                and self.scenario.rounds > 0
                and self.current_block > self._joinmarket_completion_block_limit()
            ):
                raise RuntimeError(
                    f"JoinMarket scenario did not complete {self.scenario.rounds} "
                    f"round(s) within {self.current_block} simulated blocks"
                )

            self.update_invoice_payments()
            self.update_coinjoins_joinmarket()

            log.info(
                f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60),
                end="\r",
            )
            if self.scenario.blocks == 0 or self.current_block < self.scenario.blocks:
                self.node.mine_block()
            sleep(JOINMARKET_LOOP_SLEEP_SECONDS)

        log.blank_line()
        log.info("- limit reached")
        self.node.mine_block(JOINMARKET_FINAL_SETTLE_BLOCKS)
