import asyncio
from typing import cast
from unittest.mock import patch

from manager.driver import Driver
from manager.engine.base.protocols import EmulatorClient
from manager.engine.joinmarket.rounds import JoinMarketRoundsMixin
from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient


class RoundsClient:
    def __init__(self, name: str, delta: int = 0, paused: bool = False) -> None:
        self.name = name
        self.delta = delta
        self.paused = paused
        self.max_coinjoins = 0
        self.completed_coinjoins = 0
        self.updates: list[tuple[int, int]] = []
        self.error: Exception | None = None

    def is_paused(self, current_block: int) -> bool:
        return self.paused

    def update(self, current_block: int, current_round: int) -> int:
        self.updates.append((current_block, current_round))
        if self.error is not None:
            raise self.error
        return self.delta

    async def update_async(self, current_block: int, current_round: int) -> int:
        return self.update(current_block, current_round)


class RoundsHarness(JoinMarketRoundsMixin):
    def __init__(self, *clients: RoundsClient) -> None:
        self.clients = [cast(EmulatorClient, client) for client in clients]
        self.driver = cast(Driver, None)
        self.obwatch_client: OrderbookWatchClient | None = None
        self.async_updates = True
        self.last_resource_check = 0
        self.current_block = 4
        self.current_round = 0


class TestUpdateCoinjoins:
    def test_every_client_is_ticked_with_the_current_block_and_round(self) -> None:
        first = RoundsClient("jcs-000")
        second = RoundsClient("jcs-001")
        harness = RoundsHarness(first, second)

        harness.update_coinjoins_joinmarket()

        assert first.updates == [(4, 0)]
        assert second.updates == [(4, 0)]

    def test_reported_rounds_are_added_to_the_engine_counter(self) -> None:
        harness = RoundsHarness(RoundsClient("jcs-000", delta=1), RoundsClient("jcs-001", delta=2))

        harness.update_coinjoins_joinmarket()

        assert harness.current_round == 3

    def test_later_clients_see_the_round_started_by_an_earlier_one(self) -> None:
        first = RoundsClient("jcs-000", delta=1)
        second = RoundsClient("jcs-001")
        harness = RoundsHarness(first, second)

        harness.update_coinjoins_joinmarket()

        assert second.updates == [(4, 1)]

    def test_failing_client_does_not_stop_the_others(self) -> None:
        failing = RoundsClient("jcs-000")
        failing.error = Exception("client unreachable")
        healthy = RoundsClient("jcs-001", delta=1)
        harness = RoundsHarness(failing, healthy)

        harness.update_coinjoins_joinmarket()

        assert healthy.updates == [(4, 0)]
        assert harness.current_round == 1

    def test_orderbook_watcher_is_ticked_last(self) -> None:
        watcher = RoundsClient("obwatch")
        harness = RoundsHarness(RoundsClient("jcs-000", delta=1))
        harness.obwatch_client = cast(OrderbookWatchClient, watcher)

        harness.update_coinjoins_joinmarket()

        assert watcher.updates == [(4, 1)]

    def test_failing_orderbook_watcher_is_tolerated(self) -> None:
        watcher = RoundsClient("obwatch")
        watcher.error = Exception("watcher unreachable")
        harness = RoundsHarness(RoundsClient("jcs-000", delta=1))
        harness.obwatch_client = cast(OrderbookWatchClient, watcher)

        harness.update_coinjoins_joinmarket()

        assert harness.current_round == 1


class TestUpdateCoinjoinsAsync:
    def test_all_clients_are_ticked_concurrently(self) -> None:
        first = RoundsClient("jcs-000", delta=1)
        second = RoundsClient("jcs-001", delta=1)
        harness = RoundsHarness(first, second)

        with patch("manager.engine.joinmarket.rounds.asyncio.sleep"):
            asyncio.run(harness.update_coinjoins_joinmarket_async())

        assert first.updates == [(4, 0)]
        assert second.updates == [(4, 0)]
        assert harness.current_round == 2

    def test_failing_client_is_reported_as_no_progress(self) -> None:
        failing = RoundsClient("jcs-000")
        failing.error = Exception("client unreachable")
        harness = RoundsHarness(failing, RoundsClient("jcs-001", delta=1))

        with patch("manager.engine.joinmarket.rounds.asyncio.sleep"):
            asyncio.run(harness.update_coinjoins_joinmarket_async())

        assert harness.current_round == 1

    def test_orderbook_watcher_is_updated_too(self) -> None:
        watcher = RoundsClient("obwatch")
        harness = RoundsHarness(RoundsClient("jcs-000"))
        harness.obwatch_client = cast(OrderbookWatchClient, watcher)

        with patch("manager.engine.joinmarket.rounds.asyncio.sleep"):
            asyncio.run(harness.update_coinjoins_joinmarket_async())

        assert watcher.updates == [(4, 0)]
