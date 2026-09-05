"""Prepare the shared Core wallet before starting JoinMarket services."""

from unittest.mock import Mock, call

from manager.engine.joinmarket_engine import JoinmarketEngine


def test_shared_core_wallet_is_ready_before_services_start() -> None:
    instance = object.__new__(JoinmarketEngine)
    instance.node = Mock()
    instance.start_irc_server = Mock()
    instance.start_orderbook_watch = Mock()
    startup = Mock()
    startup.attach_mock(instance.node, "node")
    startup.attach_mock(instance.start_irc_server, "irc")
    startup.attach_mock(instance.start_orderbook_watch, "watcher")

    instance.start_engine_infrastructure()

    assert startup.mock_calls == [
        call.node.create_wallet("jm_wallet", disable_private_keys=True),
        call.irc(),
        call.watcher(),
    ]
