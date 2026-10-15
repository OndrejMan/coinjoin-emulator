"""A taker starts a new attempt only after its previous one was mined or gave up."""

import asyncio

import pytest

from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import TakerClient


class OfflineTaker(TakerClient):
    """A taker whose jmwalletd RPCs are replaced by recorded answers."""

    def __init__(self, in_process: bool = False) -> None:
        super().__init__(name="jcs-000", type="taker", offers=[{"amount_sats": 100000, "counterparties": 3, "mixdepth": 0}])
        self.reported_in_process = in_process
        self.started: list[str] = []
        self.lose_start_answer = False
        self.addresses = iter(f"bcrt1q{index}" for index in range(100))

    def update_status(self):  # type: ignore[override]
        self.coinjoin_in_process = self.reported_in_process
        return {"coinjoin_in_process": self.reported_in_process}

    async def update_status_async(self):  # type: ignore[override]
        return {"coinjoin_in_process": self.reported_in_process}

    def get_new_address(self, mixdepth=0):
        return next(self.addresses)

    def start_coinjoin(self, mixdepth, amount_sats, counterparties, destination, txfee=None):  # type: ignore[override]
        self.started.append(destination)
        if self.lose_start_answer:
            raise TimeoutError("jmwalletd did not answer")
        return {}

    async def start_coinjoin_async(self, mixdepth, amount_sats, counterparties, destination, txfee=None):  # type: ignore[override]
        return self.start_coinjoin(mixdepth, amount_sats, counterparties, destination, txfee)

    def update_now(self, current_block: int, current_round: int) -> int:
        return asyncio.run(self.update_async(current_block, current_round))


def test_a_free_taker_starts_an_attempt_and_records_it() -> None:
    taker = OfflineTaker()

    assert taker.update(current_block=5, current_round=0) == 1
    assert taker.started == ["bcrt1q0"]
    assert [event["status"] for event in taker.round_events] == ["started"]
    assert [event["execution_status"] for event in taker.round_events] == ["started"]
    assert taker.has_unconfirmed_round()


def test_the_attempt_is_on_record_before_jmwalletd_is_asked() -> None:
    taker = OfflineTaker()
    seen: list[list[str]] = []
    original = taker.start_coinjoin

    def observing_start(**offer):
        seen.append([str(event["execution_status"]) for event in taker.round_events])
        return original(**offer)

    taker.start_coinjoin = observing_start  # type: ignore[method-assign]

    taker.update(current_block=5, current_round=0)

    assert seen == [["requested"]]


@pytest.mark.parametrize("path", ["sync", "async"])
def test_a_lost_start_answer_keeps_the_attempt_pending_for_the_chain(path: str) -> None:
    taker = OfflineTaker()
    taker.lose_start_answer = True
    update = taker.update if path == "sync" else taker.update_now

    with pytest.raises(TimeoutError):
        update(current_block=5, current_round=0)

    assert taker.started == ["bcrt1q0"]
    assert taker.round_events[0]["destination_address"] == "bcrt1q0"
    assert taker.round_events[0]["status"] == "started"
    assert taker.round_events[0]["execution_status"] == "unknown"
    assert taker.coinjoin_start == 5

    # jmwalletd may have run the request: no new attempt starts and the chain
    # reconciliation confirms or times out this one like any other attempt.
    taker.lose_start_answer = False
    assert update(current_block=6, current_round=0) == 0
    assert taker.started == ["bcrt1q0"]
    assert update(current_block=14, current_round=0) == -1

    taker.round_events[0]["status"] = "confirmed"
    assert update(current_block=15, current_round=1) == 1
    assert taker.started == ["bcrt1q0", "bcrt1q1"]


def test_a_taker_waits_while_its_previous_attempt_is_unconfirmed() -> None:
    taker = OfflineTaker()
    taker.update(current_block=5, current_round=0)

    assert taker.update(current_block=9, current_round=0) == 0
    assert taker.started == ["bcrt1q0"]


def test_an_attempt_that_cannot_land_any_more_is_reported_as_timed_out() -> None:
    taker = OfflineTaker()
    taker.update(current_block=5, current_round=0)

    assert taker.update(current_block=13, current_round=0) == 0
    assert taker.update(current_block=14, current_round=0) == -1


def test_an_unconfirmed_attempt_uses_the_configured_timeout() -> None:
    taker = OfflineTaker()
    taker.coinjoin_timeout_blocks = 2
    taker.update(current_block=5, current_round=0)

    assert taker.update(current_block=7, current_round=0) == 0
    assert taker.update(current_block=8, current_round=0) == -1


def test_a_confirmed_attempt_frees_the_taker_for_the_next_one() -> None:
    taker = OfflineTaker()
    taker.update(current_block=5, current_round=0)
    taker.round_events[0]["status"] = "confirmed"

    assert taker.update(current_block=6, current_round=1) == 1
    assert taker.started == ["bcrt1q0", "bcrt1q1"]


def test_the_async_path_paces_like_the_sync_one() -> None:
    taker = OfflineTaker()

    assert taker.update_now(current_block=5, current_round=0) == 1
    assert taker.update_now(current_block=9, current_round=0) == 0
    taker.round_events[0]["status"] = "confirmed"
    assert taker.update_now(current_block=10, current_round=1) == 1
    assert taker.started == ["bcrt1q0", "bcrt1q1"]


def test_a_finished_attempt_counts_towards_max_coinjoins_only_once_mined() -> None:
    taker = OfflineTaker()
    taker.max_coinjoins = 1
    taker.update(current_block=5, current_round=0)

    taker.reported_in_process = False
    assert taker.update(current_block=6, current_round=0) == 0
    assert taker.completed_coinjoins == 0
    assert not taker.is_paused(6)

    taker.round_events[0]["status"] = "confirmed"
    assert taker.update(current_block=7, current_round=1) == 0
    assert taker.completed_coinjoins == 1
    assert taker.is_paused(7)
    assert taker.started == ["bcrt1q0"]


def test_the_async_path_counts_only_mined_attempts() -> None:
    taker = OfflineTaker()
    taker.max_coinjoins = 1
    taker.update_now(current_block=5, current_round=0)

    taker.reported_in_process = False
    assert taker.update_now(current_block=6, current_round=0) == 0
    assert taker.completed_coinjoins == 0
    assert not taker.is_paused(6)

    taker.round_events[0]["status"] = "confirmed"
    assert taker.update_now(current_block=7, current_round=1) == 0
    assert taker.completed_coinjoins == 1
    assert taker.is_paused(7)
    assert taker.started == ["bcrt1q0"]


def test_a_paused_taker_still_reports_its_pending_attempt_as_timed_out() -> None:
    taker = OfflineTaker()
    taker.max_coinjoins = 1
    taker.update_now(current_block=5, current_round=0)
    taker.reported_in_process = False
    taker.completed_coinjoins = 1  # the limit was reached by an earlier, confirmed round

    assert taker.is_paused(14)
    assert taker.update_now(current_block=14, current_round=1) == -1
