import pytest

from manager.exceptions import CoinjoinEmulatorError
from manager.wasabi_clients.joinmarket_clients.bonds import JoinMarketFidelityBondMixin
from manager.wasabi_clients.joinmarket_clients.types import BTC, BondRecord, JsonDict


class BondHarness(JoinMarketFidelityBondMixin):
    def __init__(self, response: JsonDict | None = None) -> None:
        self.name = "jcs-000"
        self.walletname = "wallet.jmdat"
        self.has_fidelity_bonds = True
        self.fidelity_bonds: dict[str, BondRecord] = {}
        self.response: JsonDict = response if response is not None else {"address": "bcrt1qbond"}
        self.calls: list[tuple[str, str]] = []

    def _rpc(
        self,
        method: str,
        endpoint: str,
        json_data: JsonDict | None = None,
        timeout: int = 60,
        repeat: int = 4,
    ) -> JsonDict:
        self.calls.append((method, endpoint))
        return self.response


class TestCreateFidelityBond:
    def test_bond_is_requested_from_the_timelock_endpoint(self) -> None:
        harness = BondHarness()

        harness.create_fidelity_bond(amount=50000, locktime="2026-08", current_block=7)

        assert harness.calls == [("GET", "/wallet/wallet.jmdat/address/timelock/new/2026-08")]

    def test_created_bond_is_returned_and_tracked(self) -> None:
        harness = BondHarness()

        bond = harness.create_fidelity_bond(amount=50000, locktime="2026-08", current_block=7)

        assert bond == {
            "address": "bcrt1qbond",
            "amount": 50000,
            "locktime": "2026-08",
            "creation_block": 7,
        }
        assert harness.get_fidelity_bonds() == {
            "bcrt1qbond": {
                "amount": 50000,
                "locktime": "2026-08",
                "creation_block": 7,
                "funded": False,
            }
        }

    def test_missing_address_in_the_response_is_reported(self) -> None:
        harness = BondHarness(response={"error": "no timelock address"})

        with pytest.raises(CoinjoinEmulatorError, match="Failed to create fidelity bond"):
            harness.create_fidelity_bond(amount=50000, locktime="2026-08")

        assert harness.fidelity_bonds == {}

    def test_tracked_bonds_are_returned_as_a_copy(self) -> None:
        harness = BondHarness()
        harness.create_fidelity_bond(amount=50000, locktime="2026-08")

        harness.get_fidelity_bonds().clear()

        assert "bcrt1qbond" in harness.fidelity_bonds


class TestBondValue:
    def test_unfunded_bond_has_no_value(self) -> None:
        harness = BondHarness()
        harness.create_fidelity_bond(amount=BTC, locktime="2026-08", current_block=0)

        assert harness.get_bond_value("bcrt1qbond", current_block=288) == 0.0

    def test_bond_value_grows_with_the_blocks_it_was_held_for(self) -> None:
        harness = BondHarness()
        harness.create_fidelity_bond(amount=BTC, locktime="2026-08", current_block=0)
        harness.mark_bond_funded("bcrt1qbond")

        assert harness.get_bond_value("bcrt1qbond", current_block=72) == 0.5

    def test_bond_value_is_capped_after_a_day(self) -> None:
        harness = BondHarness()
        harness.create_fidelity_bond(amount=BTC, locktime="2026-08", current_block=0)
        harness.mark_bond_funded("bcrt1qbond")

        assert harness.get_bond_value("bcrt1qbond", current_block=1000) == 1.0

    def test_unknown_address_has_no_value(self) -> None:
        assert BondHarness().get_bond_value("bcrt1qunknown") == 0.0

    def test_marking_an_unknown_address_leaves_the_tracked_bonds_alone(self) -> None:
        harness = BondHarness()

        harness.mark_bond_funded("bcrt1qunknown")

        assert harness.fidelity_bonds == {}


class TestExportFidelityBondsData:
    def test_export_without_bonds_reports_the_wallet_type(self) -> None:
        harness = BondHarness()
        harness.has_fidelity_bonds = False

        data = harness.export_fidelity_bonds_data()

        assert data["client_name"] == "jcs-000"
        assert data["wallet_name"] == "wallet.jmdat"
        assert data["wallet_type"] == "sw"
        assert data["bonds"] == []
        assert data["total_bonds"] == 0
        assert data["total_amount_satoshis"] == 0

    def test_export_totals_the_tracked_bonds(self) -> None:
        harness = BondHarness()
        harness.create_fidelity_bond(amount=BTC, locktime="2026-08", current_block=0)
        harness.mark_bond_funded("bcrt1qbond")

        data = harness.export_fidelity_bonds_data(current_block=144)

        assert data["wallet_type"] == "sw-fb"
        assert data["total_bonds"] == 1
        assert data["total_amount_satoshis"] == BTC
        assert data["total_amount_btc"] == 1.0
        assert data["total_bond_value"] == 1.0

    def test_unfunded_bond_is_exported_with_no_holding_time(self) -> None:
        harness = BondHarness()
        harness.create_fidelity_bond(amount=50000, locktime="2026-08", current_block=1)

        bonds = harness.export_fidelity_bonds_data(current_block=144)["bonds"]

        assert isinstance(bonds, list)
        assert bonds[0]["funded"] is False
        assert bonds[0]["blocks_held"] == 0
        assert bonds[0]["bond_value"] == 0.0
