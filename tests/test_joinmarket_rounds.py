"""Round accounting: an RPC start is an attempt, not a completed CoinJoin."""

import threading
from types import SimpleNamespace

from manager.engine.joinmarket_engine import JoinmarketEngine


class RoundsClient:
    def __init__(self, name: str, delta: int = 0) -> None:
        self.name = name
        self.type = "taker"
        self.delta = delta
        self.max_coinjoins = 0
        self.round_events: list[dict[str, object]] = []
        self.updates: list[tuple[int, int]] = []

    def is_paused(self, current_block: int) -> bool:
        return False

    def update(self, current_block: int, current_round: int) -> int:
        self.updates.append((current_block, current_round))
        return self.delta


def harness(*clients: RoundsClient) -> JoinmarketEngine:
    engine = object.__new__(JoinmarketEngine)
    engine.args = SimpleNamespace()
    engine.clients = list(clients)
    engine.obwatch_client = None
    engine._obwatch_missing_logged = True  # pylint: disable=protected-access
    engine._core_wallet_lock = threading.Lock()  # pylint: disable=protected-access
    engine._round_scan_height = -1  # pylint: disable=protected-access
    engine.node = None
    engine.current_block = 4
    engine.current_round = 0
    return engine


def test_an_rpc_start_does_not_advance_the_round_counter() -> None:
    engine = harness(RoundsClient("jcs-000", delta=1), RoundsClient("jcs-001", delta=2))

    engine.update_coinjoins_joinmarket()

    assert engine.current_round == 0


def test_a_timed_out_attempt_is_marked_failed_without_changing_the_counter() -> None:
    client = RoundsClient("jcs-000", delta=-1)
    client.round_events.append({"taker": client.name, "status": "started"})
    engine = harness(client)

    engine.update_coinjoins_joinmarket()

    assert engine.current_round == 0
    assert client.round_events[0]["status"] == "failed"
    assert client.round_events[0]["stop_block"] == 4
