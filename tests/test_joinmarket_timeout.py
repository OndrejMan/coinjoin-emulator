"""Configurable timeout boundaries for JoinMarket client attempts."""

from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import (
    DEFAULT_COINJOIN_TIMEOUT_BLOCKS,
    JoinMarketClientServer,
)


def test_coinjoin_timeout_defaults_to_eight_blocks() -> None:
    client = JoinMarketClientServer()
    client.coinjoin_start = 5

    assert client.coinjoin_timeout_blocks == DEFAULT_COINJOIN_TIMEOUT_BLOCKS == 8
    assert not client.coinjoin_timed_out(13)
    assert client.coinjoin_timed_out(14)


def test_coinjoin_timeout_uses_the_configured_block_limit() -> None:
    client = JoinMarketClientServer(coinjoin_timeout_blocks=2)
    client.coinjoin_start = 5

    assert not client.coinjoin_timed_out(7)
    assert client.coinjoin_timed_out(8)
