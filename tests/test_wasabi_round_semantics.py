"""Wasabi round accounting for the split backend architecture."""

from unittest.mock import Mock, patch

from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.engine.wasabi_engine import WasabiEngine
from manager.wasabi_backend_factory import BackendArchitecture


def split_engine() -> WasabiEngine:
    engine = object.__new__(WasabiEngine)
    engine.backend_architecture = BackendArchitecture.SPLIT
    engine.driver = Mock()
    return engine


def test_only_successfully_broadcast_transactions_count_as_rounds() -> None:
    engine = split_engine()
    txid_a, txid_b = "a" * 64, "b" * 64
    engine.driver.peek.return_value = "\n".join(
        [
            f"Successfully broadcasted coinjoin transaction: {txid_a}",
            f"Successfully broadcasted coinjoin transaction: {txid_a}",
            f"Successfully broadcasted coinjoin transaction: {txid_b}",
        ]
    )

    assert engine._get_current_round() == 2  # pylint: disable=protected-access


def test_the_run_stops_after_the_requested_number_of_rounds() -> None:
    engine = split_engine()
    engine.node = Mock()
    engine.node.get_block_count.return_value = 100
    engine.node.mine_block.return_value = True
    engine.scenario = ScenarioConfig("test", 1, 0, "test", [WalletConfig(funds=[1])])
    engine.current_round = 0
    engine.current_block = 0
    engine._get_current_round = Mock(return_value=1)  # pylint: disable=protected-access
    engine.update_invoice_payments = Mock()
    engine.update_coinjoins = Mock()

    with patch("manager.engine.wasabi_engine.sleep"):
        engine.run_engine()

    engine._get_current_round.assert_called_once_with()  # pylint: disable=protected-access
    engine.node.mine_block.assert_called_once_with(3)
