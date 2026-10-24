"""JoinMarket wallets mix only inside their start and stop schedule, as Wasabi wallets do."""

import asyncio

import pytest

from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import MakerClient, TakerClient


class OfflineMaker(MakerClient):
    """A maker whose jmwalletd answers are recorded instead of sent."""

    def __init__(self, delay: tuple[int, int] = (0, 0), stop: tuple[int, int] = (0, 0)) -> None:
        super().__init__(name="jcs-001", type="maker", delay=delay, stop=stop, offers=[{"ordertype": "sw0reloffer"}])
        self.calls: list[str] = []

    def update_status(self):  # type: ignore[override]
        return {"maker_running": self.maker_running}

    async def update_status_async(self):  # type: ignore[override]
        return {"maker_running": self.maker_running}

    def start_maker(self, **offer):  # type: ignore[override]
        self.calls.append("start")

    async def start_maker_async(self, **offer):  # type: ignore[override]
        self.calls.append("start")

    def stop_maker(self):  # type: ignore[override]
        self.calls.append("stop")

    async def stop_maker_async(self):  # type: ignore[override]
        self.calls.append("stop")


class OfflineTaker(TakerClient):
    def __init__(self, delay: tuple[int, int] = (0, 0), stop: tuple[int, int] = (0, 0)) -> None:
        super().__init__(name="jcs-000", type="taker", delay=delay, stop=stop, offers=[{"amount_sats": 1, "counterparties": 3, "mixdepth": 0}])
        self.started = 0

    def update_status(self):  # type: ignore[override]
        return {"coinjoin_in_process": False}

    def get_new_address(self, mixdepth=0):
        return f"bcrt1q{self.started}"

    def start_coinjoin(self, mixdepth, amount_sats, counterparties, destination, txfee=None):  # type: ignore[override]
        self.started += 1


@pytest.mark.parametrize(
    ("delay", "stop", "block", "round_", "outside"),
    [
        ((5, 0), (0, 0), 4, 9, True),
        ((5, 0), (0, 0), 5, 0, False),
        ((0, 3), (0, 0), 50, 2, True),
        ((0, 3), (0, 0), 0, 3, False),
        ((0, 0), (20, 0), 20, 0, True),
        ((0, 0), (0, 6), 0, 6, True),
        ((0, 0), (0, 6), 19, 5, False),
    ],
)
def test_schedule_matches_wasabi_start_condition(delay, stop, block, round_, outside) -> None:
    assert OfflineTaker(delay, stop).outside_schedule(block, round_) is outside


def test_taker_starts_no_coinjoin_before_its_start_round_or_after_its_stop() -> None:
    taker = OfflineTaker(delay=(0, 2), stop=(0, 4))

    taker.update(current_block=10, current_round=1)
    assert taker.started == 0
    taker.update(current_block=10, current_round=2)
    assert taker.started == 1

    taker.round_events.clear()
    taker.update(current_block=11, current_round=4)
    assert taker.started == 1


@pytest.mark.parametrize("run_async", [False, True])
def test_maker_offers_only_inside_its_schedule(run_async: bool) -> None:
    maker = OfflineMaker(delay=(3, 0), stop=(0, 5))

    def update(block: int, round_: int) -> None:
        if run_async:
            asyncio.run(maker.update_async(block, round_))
        else:
            maker.update(block, round_)

    update(2, 0)
    assert maker.calls == []
    update(3, 0)
    update(4, 4)
    assert (maker.calls, maker.maker_running) == (["start"], True)
    update(6, 5)
    assert (maker.calls, maker.maker_running) == (["start", "stop"], False)
    update(7, 6)
    assert maker.calls == ["start", "stop"]


def test_tumbler_gets_a_unique_schedule_file_without_changing_the_scenario() -> None:
    from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import TumblerTakerClient

    options = {"mixdepthcount": 3}
    first = TumblerTakerClient(name="jcs-002", type="taker", tumbler_options=options)
    second = TumblerTakerClient(name="jcs-002", type="taker", tumbler_options=options)

    assert options == {"mixdepthcount": 3}
    assert first.tumbler_options["schedulefile"].startswith("TUMBLE.schedule_")
    assert first.tumbler_options["schedulefile"] != second.tumbler_options["schedulefile"]
    named = TumblerTakerClient(name="jcs-003", type="taker", tumbler_options={"schedulefile": "mine"})
    assert named.tumbler_options["schedulefile"].startswith("mine_")
