"""Funding of the distributor and of the wallet invoices."""

import math
import random
from time import sleep
from typing import TYPE_CHECKING

from manager import utils
from manager.btc_node import BtcNode
from manager.engine.base.protocols import EmulatorClient, InvoiceDistributor
from manager.engine.configuration import FundConfig, WalletConfig

DISTRIBUTOR_UTXOS = 200
BATCH_SIZE = 5  # smaller batches avoid UTXO race conditions
BTC = 100_000_000


class EngineFundingMixin:
    """Tops the distributor up and pays out the per-wallet funding invoices."""

    clients: list[EmulatorClient]
    distributor: InvoiceDistributor | None
    node: BtcNode | None
    current_block: int
    current_round: int
    invoices: dict[tuple[int, int], list[tuple[str, int]]]

    if TYPE_CHECKING:
        pass

    def fund_distributor(self, btc_amount: int | float) -> None:
        print("Funding distributor")
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        if self.distributor is None:
            raise RuntimeError("Distributor is not initialized")

        # Round each UTXO up to a whole satoshi so the total meets the target
        # even when the amount does not divide evenly. Integer-dividing by BTC
        # here would fund every address with 0 BTC for any total below 200 BTC.
        per_utxo_sats = math.ceil(btc_amount * BTC / DISTRIBUTOR_UTXOS)
        for _ in range(DISTRIBUTOR_UTXOS):
            self.node.fund_address(
                self.distributor.get_new_address(),
                # Bitcoin Core rejects scientific notation, so keep 8 decimals.
                float(f"{per_utxo_sats / BTC:.8f}"),
            )

        while (balance := self.distributor.get_balance()) < btc_amount * BTC:
            sleep(1)
        print(f"- funded (current balance {balance / BTC:.8f} BTC)")

    def update_invoice_payments(self) -> None:
        due = list(filter(lambda x: x[0] <= self.current_block and x[1] <= self.current_round, self.invoices.keys()))
        for i in due:
            self.pay_invoices(self.invoices.pop(i, []))

    def prepare_invoices(self, wallets: list[WalletConfig]) -> None:
        print("Preparing invoices")
        client_invoices = [(client, wallet.funds) for client, wallet in zip(self.clients, wallets)]

        for client, funds in client_invoices:
            for fund in funds:
                block = 0
                round = 0
                if isinstance(fund, int):
                    value = fund
                elif isinstance(fund, FundConfig):
                    value = fund.value
                    block = fund.delay_blocks or 0
                    round = fund.delay_rounds or 0
                else:
                    raise TypeError(f"unsupported fund entry for {client.name}: {fund!r}")
                addressed_invoice = (client.get_new_address(), value)
                if (block, round) not in self.invoices:
                    self.invoices[(block, round)] = [addressed_invoice]
                else:
                    self.invoices[(block, round)].append(addressed_invoice)

        for addressed_invoices in self.invoices.values():
            random.shuffle(addressed_invoices)

        print(f"- prepared {sum(map(len, self.invoices.values()))} invoices")

    def pay_invoices(self, addressed_invoices: list[tuple[str, int]]) -> None:
        print(
            f"- paying {len(addressed_invoices)} invoices (batch size {BATCH_SIZE}, "
            f"block {self.current_block}, round {self.current_round})"
        )
        try:
            for batch in utils.batched(addressed_invoices, BATCH_SIZE):
                for _ in range(3):
                    try:
                        if self.distributor is None:
                            raise RuntimeError("Distributor is not initialized")
                        result = self.distributor.send(batch)
                        if str(result) == "timeout":
                            print("- transaction timeout")
                            continue
                        break
                    except Exception as e:
                        # https://github.com/zkSNACKs/WalletWasabi/issues/12764
                        if "Bad Request" in str(e):
                            print("- transaction error (bad request)")
                        else:
                            print(f"- transaction error ({e})")
                else:
                    print("- invoice payment failed")
                    raise Exception("Invoice payment failed")

        except Exception as e:
            print("- invoice payment failed")
            raise e

    def prepare_additional_funding(self, wallets: list[WalletConfig]) -> None:
        """
        Hook for engines to perform additional post-funding setup.
        Default implementation does nothing.

        Args:
            wallets: List of wallet configurations
        """
        pass
