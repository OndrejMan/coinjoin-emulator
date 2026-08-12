"""Fidelity bond creation and its funding round."""

# The sibling methods are declared under TYPE_CHECKING, so pylint cannot see
# that they return a value.
# pylint: disable=assignment-from-no-return

from typing import TYPE_CHECKING, cast

from manager.btc_node import BtcNode
from manager.engine.base.protocols import EmulatorClient, InvoiceDistributor
from manager.engine.configuration import WalletConfig
from manager.exceptions import CoinjoinEmulatorError
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer


class JoinMarketFundingMixin:
    """Creates the configured fidelity bonds and pays their invoices."""

    clients: list[EmulatorClient]
    distributor: InvoiceDistributor | None
    current_block: int
    node: BtcNode | None

    if TYPE_CHECKING:
        # pylint: disable=unused-argument  # these are stub signatures
        def pay_invoices(self, addressed_invoices: list[tuple[str, int]]) -> None: ...
        def update_invoice_payments(self) -> None: ...

    def prepare_additional_funding(self, wallets: list[WalletConfig]) -> None:
        """
        JoinMarket-specific additional funding setup.
        Creates and funds fidelity bonds for wallets that have bond configuration.
        """
        bond_clients = []
        bond_invoices = []

        print("Preparing fidelity bonds")

        for client, wallet in zip(self.clients, wallets):
            fidelity_bond_config = (wallet.joinmarket.fidelity_bond if wallet.joinmarket else None) or {}

            if not fidelity_bond_config.get("enabled", False):
                continue

            try:
                # Extract bond configuration
                amount = fidelity_bond_config.get("amount", 50000)  # Default 50k sats
                locktime = fidelity_bond_config.get("locktime")

                if not locktime:
                    print(f"Warning: No locktime specified for fidelity bond on {client.name}, skipping")
                    continue

                # Create the bond
                jm_client = cast(JoinMarketClientServer, client)
                bond_info = jm_client.create_fidelity_bond(
                    amount=int(cast(int, amount)),
                    locktime=str(locktime),
                    current_block=self.current_block
                )

                # Prepare funding invoice
                bond_address = str(bond_info["address"])
                bond_invoice = (bond_address, int(cast(int, amount)))
                bond_invoices.append(bond_invoice)
                bond_clients.append((client, bond_address))

                print(f"- prepared fidelity bond for {client.name}: {amount} sats to {bond_address}")

            except Exception as e:
                print(f"Error creating fidelity bond for {client.name}: {e}")
                raise CoinjoinEmulatorError(f"Failed to create fidelity bond for {client.name}: {e}") from e

        if bond_invoices:
            print(f"Funding {len(bond_invoices)} fidelity bonds")

            try:
                # Fund all bonds in a single batch
                self.pay_invoices(bond_invoices)

                # Mark bonds as funded
                for bond_client, bond_address in bond_clients:
                    cast(JoinMarketClientServer, bond_client).mark_bond_funded(bond_address)

                print(f"- funded {len(bond_invoices)} fidelity bonds")

                # Mine additional blocks to ensure fidelity bond transactions are confirmed
                # JoinMarket needs confirmed UTXOs to calculate bond values for maker offers
                print("Mining blocks to confirm fidelity bond transactions")
                if self.node is None:
                    raise RuntimeError("Bitcoin node is not initialized")
                for _ in range(15):  # Mine 15 blocks for solid confirmation
                    self.node.mine_block()
                print("- fidelity bond confirmations completed")

            except Exception as e:
                print(f"Failed to fund fidelity bonds: {e}")
                raise CoinjoinEmulatorError(f"Failed to fund fidelity bonds: {e}") from e
        else:
            print("- no fidelity bonds to fund")
