"""A run limited by rounds must end with its data once its rounds stop completing."""

import json
from itertools import chain, repeat
from types import SimpleNamespace
from unittest.mock import Mock, patch

from manager.engine.wasabi_engine import DEFAULT_ROUND_STALL_TIMEOUT, EARLY_END_FILE, WasabiEngine

TEN_MINUTES = 600


class Clock:
    """Time that moves only while the engine sleeps between two polls."""

    def __init__(self, poll_seconds: float) -> None:
        self.now = 1_000.0
        self.poll_seconds = poll_seconds

    def time(self) -> float:
        return self.now

    def sleep(self, _seconds: float) -> None:
        self.now += self.poll_seconds


def polled_engine(rounds, *, limit=40, blocks=0, timeout=DEFAULT_ROUND_STALL_TIMEOUT) -> WasabiEngine:
    """An engine whose coordinator reports the coinjoin counts in ``rounds``, one per poll."""
    engine = object.__new__(WasabiEngine)
    engine.round_stall_timeout = timeout
    engine.scenario = SimpleNamespace(rounds=limit, blocks=blocks)
    engine.current_round = 0
    engine.current_block = 0
    engine.postmix_spends = None
    engine.node = Mock()
    engine.node.get_block_count.return_value = 100
    engine._get_current_round = Mock(side_effect=rounds)
    engine.update_invoice_payments = Mock()
    engine.update_postmix_spends = Mock()
    engine.update_coinjoins = Mock()
    engine.mine_settlement_blocks = Mock()
    return engine


def run(engine: WasabiEngine, poll_seconds: float) -> None:
    clock = Clock(poll_seconds)
    with (
        patch("manager.engine.wasabi_engine.time", clock.time),
        patch("manager.engine.wasabi_engine.sleep", clock.sleep),
    ):
        engine.run_engine()


def test_a_run_whose_rounds_stop_ends_early_and_settles(capsys) -> None:
    engine = polled_engine(chain([1, 2, 3], repeat(3)))

    run(engine, TEN_MINUTES)

    assert engine.early_end == {
        "schema_version": "1.0",
        "reason": "round_stall",
        "rounds_completed": 3,
        "rounds_planned": 40,
        "block": 0,
        "seconds_without_round": DEFAULT_ROUND_STALL_TIMEOUT,
        "round_stall_timeout": DEFAULT_ROUND_STALL_TIMEOUT,
    }
    # The poll that finds the stall pays, spends and mixes nothing more.
    polls = engine._get_current_round.call_count
    assert polls == 3 + DEFAULT_ROUND_STALL_TIMEOUT // TEN_MINUTES
    assert engine.update_invoice_payments.call_count == polls - 1
    assert engine.update_postmix_spends.call_count == polls - 1
    assert engine.update_coinjoins.call_count == polls - 1
    engine.mine_settlement_blocks.assert_called_once_with()
    output = capsys.readouterr().out
    assert "ending early at round 3 of 40" in output
    assert "limit reached" not in output


def test_slow_rounds_that_keep_completing_reach_the_limit(capsys) -> None:
    # Two polls of 40 minutes pass between coinjoins, less than the 90 minutes allowed.
    engine = polled_engine([0, 0, 1, 1, 2, 2, 3], limit=3)

    run(engine, 4 * TEN_MINUTES)

    assert engine.early_end is None
    assert engine._get_current_round.call_count == 7
    engine.mine_settlement_blocks.assert_called_once_with()
    assert "limit reached" in capsys.readouterr().out


def test_a_timeout_of_zero_keeps_waiting() -> None:
    engine = polled_engine(chain(repeat(2, 20), [5]), limit=5, timeout=0)

    run(engine, 10 * DEFAULT_ROUND_STALL_TIMEOUT)

    assert engine.early_end is None
    assert engine._get_current_round.call_count == 21


def test_a_block_limit_ends_the_run_by_itself() -> None:
    engine = polled_engine(repeat(2), blocks=6)
    engine.node.get_block_count.side_effect = range(100, 107)

    run(engine, 10 * DEFAULT_ROUND_STALL_TIMEOUT)

    assert engine.early_end is None
    assert engine.current_block == 6


def test_the_early_end_is_stored_with_the_run_data(tmp_path) -> None:
    engine = polled_engine(repeat(0))
    run(engine, TEN_MINUTES)

    engine.store_engine_data(str(tmp_path))

    assert json.loads((tmp_path / EARLY_END_FILE).read_text(encoding="utf-8")) == engine.early_end
    assert engine.early_end["rounds_completed"] == 0


def test_a_run_that_reached_its_limit_stores_no_early_end(tmp_path) -> None:
    engine = polled_engine([1, 2], limit=2)
    run(engine, TEN_MINUTES)

    engine.store_engine_data(str(tmp_path))

    assert not (tmp_path / EARLY_END_FILE).exists()
