"""Wasabi round accounting for the split backend architecture."""

from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.engine.wasabi_engine import WasabiEngine, successful_broadcast_txids
from manager.wasabi_backend_factory import BackendArchitecture


def split_engine() -> WasabiEngine:
    engine = object.__new__(WasabiEngine)
    engine.backend_architecture = BackendArchitecture.SPLIT
    engine.driver = Mock()
    return engine


def test_successful_broadcast_txids_are_deduplicated_across_logs() -> None:
    txid_a, txid_b = "a" * 64, "B" * 64

    assert successful_broadcast_txids(
        [
            f"Successfully broadcasted coinjoin transaction: {txid_a}",
            "\n".join(
                [
                    f"Successfully broadcasted coinjoin transaction: {txid_a}",
                    f"Successfully broadcast coinjoin: {txid_b}",
                ]
            ),
        ]
    ) == {txid_a, txid_b.lower()}


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


def test_the_run_stops_clients_before_settlement_after_the_round_limit() -> None:
    engine = split_engine()
    client = SimpleNamespace(stop=(0, 0), delay=(0, 0))
    lifecycle = Mock()
    engine.clients = [client]
    engine.start_coinjoin = lifecycle.start
    engine.stop_coinjoin = lifecycle.stop
    engine.node = Mock()
    engine.node.get_block_count.return_value = 100
    engine.node.mine_block = lifecycle.mine
    engine.scenario = ScenarioConfig("test", 1, 0, "test", [WalletConfig(funds=[1])])
    engine.current_round = 0
    engine.current_block = 0
    engine._get_current_round = Mock(return_value=1)  # pylint: disable=protected-access
    engine.update_invoice_payments = Mock()

    with patch("manager.engine.wasabi_engine.sleep"):
        engine.run_engine()

    engine._get_current_round.assert_called_once_with()  # pylint: disable=protected-access
    assert lifecycle.method_calls == [call.stop(client), call.mine(3)]
