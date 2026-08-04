"""Fidelity bond bookkeeping for the JoinMarket client."""

# The sibling methods are declared under TYPE_CHECKING, so pylint cannot see
# that they return a value.
# pylint: disable=assignment-from-no-return

from typing import TYPE_CHECKING, cast

from .types import BTC, BondRecord, JsonDict


class JoinMarketFidelityBondMixin:
    """Creates timelock addresses and tracks the bonds made from them."""

    name: str
    walletname: str
    fidelity_bonds: dict[str, BondRecord]
    has_fidelity_bonds: bool

    if TYPE_CHECKING:
        def _rpc(
            self,
            method: str,
            endpoint: str,
            json_data: JsonDict | None = None,
            timeout: int = 60,
            repeat: int = 4,
        ) -> JsonDict: ...

    def get_new_timelock_address(self, lockdate: str) -> JsonDict:
        """Get a fresh timelock address for depositing funds to create a fidelity bond."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/address/timelock/new/{lockdate}"
        response = self._rpc(method, endpoint)
        return response

    def create_fidelity_bond(self, amount: int, locktime: str, current_block: int = 0) -> JsonDict:
        """
        Create a fidelity bond by generating a timelock address and tracking it.

        Args:
            amount: Amount in satoshis to bond
            locktime: Unix timestamp when bond unlocks
            current_block: Current block height (for tracking)

        Returns:
            dict: Bond information including address
        """
        try:
            response = self.get_new_timelock_address(locktime)
            address = str(response.get("address") or "")

            if not address:
                raise Exception(f"Failed to create fidelity bond address: {response}")

            # Track the bond
            self.fidelity_bonds[address] = {
                "amount": amount,
                "locktime": locktime,
                "creation_block": current_block,
                "funded": False,
            }

            print(f"Created fidelity bond address {address} for {amount} sats until {locktime}")
            return {
                "address": address,
                "amount": amount,
                "locktime": locktime,
                "creation_block": current_block,
            }

        except Exception as e:
            raise Exception(f"Failed to create fidelity bond: {e}") from e

    def get_fidelity_bonds(self) -> dict[str, BondRecord]:
        """
        Get list of all created fidelity bonds.

        Returns:
            dict: Dictionary of bond addresses to bond info
        """
        return self.fidelity_bonds.copy()

    def mark_bond_funded(self, address: str) -> None:
        """
        Mark a fidelity bond as funded.

        Args:
            address: Bond address that was funded
        """
        if address in self.fidelity_bonds:
            self.fidelity_bonds[address]['funded'] = True
            print(f"Marked fidelity bond {address} as funded")
        else:
            print(f"Warning: Attempted to mark unknown bond address {address} as funded")

    def get_bond_value(self, address: str, current_block: int = 0) -> float:
        """
        Calculate bond value for reputation (simplified calculation).

        Args:
            address: Bond address
            current_block: Current block height

        Returns:
            float: Bond value for reputation calculation
        """
        if address not in self.fidelity_bonds:
            return 0.0

        bond = self.fidelity_bonds[address]
        if not bond['funded']:
            return 0.0

        # Simplified bond value calculation
        # In real JoinMarket, this involves complex age/amount calculations
        amount_btc = bond['amount'] / BTC
        blocks_held = max(0, current_block - bond['creation_block'])

        # Basic age-weighted value (simplified)
        age_factor = min(1.0, blocks_held / 144)  # Blocks per day
        return amount_btc * age_factor

    def export_fidelity_bonds_data(self, current_block: int = 0) -> JsonDict:
        """
        Export fidelity bond data for logging/analysis.

        Args:
            current_block: Current block height for value calculations

        Returns:
            dict: Complete fidelity bond information with calculated values
        """
        bonds_data: JsonDict = {
            "client_name": self.name,
            "wallet_name": self.walletname,
            "wallet_type": "sw-fb" if self.has_fidelity_bonds else "sw",
            "current_block": current_block,
            "bonds": []
        }

        bonds: list[JsonDict] = []
        for address, bond_info in self.fidelity_bonds.items():
            bond_data: JsonDict = {
                "address": address,
                "amount_satoshis": bond_info["amount"],
                "amount_btc": bond_info["amount"] / BTC,
                "locktime": bond_info["locktime"],
                "creation_block": bond_info["creation_block"],
                "funded": bond_info["funded"],
                "bond_value": self.get_bond_value(address, current_block),
                "blocks_held": max(0, current_block - bond_info["creation_block"]) if bond_info["funded"] else 0
            }
            bonds.append(bond_data)

        total_satoshis = sum(int(cast(int, bond["amount_satoshis"])) for bond in bonds)
        bonds_data["bonds"] = bonds
        bonds_data["total_bonds"] = len(bonds)
        bonds_data["total_amount_satoshis"] = total_satoshis
        bonds_data["total_amount_btc"] = total_satoshis / BTC
        bonds_data["total_bond_value"] = sum(float(cast(float, bond["bond_value"])) for bond in bonds)

        return bonds_data
