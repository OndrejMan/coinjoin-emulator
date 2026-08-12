from typing import cast
from unittest.mock import Mock, patch

from manager.driver import Driver
from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.engine.wasabi_engine import WasabiEngine
from manager.wasabi_backend_factory import BackendArchitecture


def split_engine() -> WasabiEngine:
    engine = object.__new__(WasabiEngine)
    engine.backend_architecture = BackendArchitecture.SPLIT
    engine.driver = cast(Driver, Mock())
    return engine


def test_split_backend_counts_successful_broadcasts_not_signing_phases() -> None:
    engine = split_engine()
    driver = cast(Mock, engine.driver)
    txid_a = "a" * 64
    txid_b = "b" * 64
    driver.peek.return_value = "\n".join(
        [
            f"Successfully broadcasted coinjoin transaction: {txid_a}",
            f"Successfully broadcasted coinjoin transaction: {txid_a}",
            f"Successfully broadcasted coinjoin transaction: {txid_b}",
        ]
    )

    assert engine._get_current_round() == 2  # pylint: disable=protected-access


def test_round_limit_stops_after_the_requested_successful_broadcast() -> None:
    engine = split_engine()
    engine.node = Mock()
    engine.node.get_block_count.return_value = 100
    engine.node.mine_block.return_value = True
    engine.scenario = ScenarioConfig("test", 1, 0, "test", [WalletConfig(funds=[1])])
    engine.current_round = 0
    engine.current_block = 0
    get_current_round = Mock(return_value=1)
    engine._get_current_round = get_current_round  # type: ignore[method-assign]  # pylint: disable=protected-access
    engine.update_invoice_payments = Mock()  # type: ignore[method-assign]
    engine.update_coinjoins = Mock()  # type: ignore[method-assign]

    with patch("manager.engine.wasabi_engine.sleep"):
        engine.run_engine()

    get_current_round.assert_called_once_with()
    engine.node.mine_block.assert_called_once_with(3)
