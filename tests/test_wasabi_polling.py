"""A polling cycle must refresh both counters before making payment or mixing decisions."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from manager.engine.wasabi_engine import COUNTER_REFRESH_DELAYS_SECONDS, WasabiEngine

ATTEMPTS = len(COUNTER_REFRESH_DELAYS_SECONDS) + 1


def polling_engine() -> WasabiEngine:
    engine = object.__new__(WasabiEngine)
    engine.scenario = SimpleNamespace(rounds=5, blocks=10)
    engine.current_round = 1
    engine.current_block = 2
    engine.node = Mock()
    engine.node.get_block_count.return_value = 100
    engine._get_current_round = Mock(return_value=5)
    engine.update_invoice_payments = Mock()
    engine.update_postmix_spends = Mock()
    engine.update_coinjoins = Mock()
    engine.mine_settlement_blocks = Mock()
    return engine


@pytest.mark.parametrize("counter", ["round", "block"])
def test_exhausted_retries_abort_before_using_stale_state(counter: str) -> None:
    engine = polling_engine()
    errors = [OSError(f"poll failure {attempt}") for attempt in range(ATTEMPTS)]
    if counter == "round":
        engine._get_current_round.side_effect = errors
    else:
        engine.node.get_block_count.side_effect = [100, *errors]

    with (
        patch("manager.engine.wasabi_engine.sleep") as sleep,
        pytest.raises(RuntimeError, match=f"{counter} count after {ATTEMPTS} attempts") as caught,
    ):
        engine.run_engine()

    assert caught.value.__cause__ is errors[-1]
    assert [call.args[0] for call in sleep.call_args_list] == list(COUNTER_REFRESH_DELAYS_SECONDS)
    assert engine._get_current_round.call_count == (ATTEMPTS if counter == "round" else 1)
    assert engine.node.get_block_count.call_count == (1 if counter == "round" else ATTEMPTS + 1)
    engine.update_invoice_payments.assert_not_called()
    engine.update_postmix_spends.assert_not_called()
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
    engine.update_postmix_spends.assert_called_once_with()
    engine.mine_settlement_blocks.assert_called_once_with()


def test_a_coordinator_exec_refused_for_half_a_minute_does_not_end_the_run() -> None:
    # The API server answered 500 to every exec into the coordinator for a while; the
    # refresh has to outlast that instead of giving up within the same second.
    engine = polling_engine()
    now = [0.0]
    outage_ends = 30.0

    def coordinator_round() -> int:
        if now[0] < outage_ends:
            raise RuntimeError("could not read Logs.txt: Handshake status 500 Internal Server Error")
        return 5

    def sleep(seconds: float) -> None:
        now[0] += seconds

    engine._get_current_round.side_effect = coordinator_round
    with patch("manager.engine.wasabi_engine.sleep", sleep), patch("manager.engine.wasabi_engine.time", lambda: now[0]):
        engine.run_engine()

    assert engine.current_round == 5
    assert engine._get_current_round.call_count == 5
    engine.update_coinjoins.assert_called_once_with()
    engine.mine_settlement_blocks.assert_called_once_with()
