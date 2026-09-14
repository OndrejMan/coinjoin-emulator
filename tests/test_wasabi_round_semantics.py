"""Wasabi round accounting for the split backend architecture."""

from unittest.mock import Mock

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
