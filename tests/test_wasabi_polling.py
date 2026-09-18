"""A polling cycle must refresh both counters before making payment or mixing decisions."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from manager.engine.wasabi_engine import WasabiEngine


def polling_engine() -> WasabiEngine:
    engine = object.__new__(WasabiEngine)
    engine.scenario = SimpleNamespace(rounds=5, blocks=10)
    engine.current_round = 1
    engine.current_block = 2
    engine.node = Mock()
    engine.node.get_block_count.return_value = 100
    engine._get_current_round = Mock(return_value=5)
    engine.update_invoice_payments = Mock()
    engine.update_coinjoins = Mock()
    engine.mine_settlement_blocks = Mock()
    return engine


@pytest.mark.parametrize("counter", ["round", "block"])
def test_exhausted_retries_abort_before_using_stale_state(counter: str) -> None:
    engine = polling_engine()
    errors = [OSError(f"poll failure {attempt}") for attempt in range(3)]
    if counter == "round":
        engine._get_current_round.side_effect = errors
    else:
        engine.node.get_block_count.side_effect = [100, *errors]

    with (
        patch("manager.engine.wasabi_engine.sleep"),
        pytest.raises(RuntimeError, match=f"{counter} count after 3 attempts") as caught,
    ):
        engine.run_engine()

    assert caught.value.__cause__ is errors[-1]
    assert engine._get_current_round.call_count == (3 if counter == "round" else 1)
    assert engine.node.get_block_count.call_count == (1 if counter == "round" else 4)
    engine.update_invoice_payments.assert_not_called()
    engine.update_coinjoins.assert_not_called()
    engine.mine_settlement_blocks.assert_not_called()


def test_third_attempt_can_refresh_both_counters() -> None:
    engine = polling_engine()
    engine._get_current_round.side_effect = [OSError("round"), OSError("round"), 5]
    engine.node.get_block_count.side_effect = [100, OSError("block"), OSError("block"), 103]
    observed = []
    engine.update_coinjoins.side_effect = lambda: observed.append((engine.current_round, engine.current_block))

    with patch("manager.engine.wasabi_engine.sleep"):
        engine.run_engine()

    assert observed == [(5, 3)]
    engine.update_invoice_payments.assert_called_once_with()
    engine.mine_settlement_blocks.assert_called_once_with()
