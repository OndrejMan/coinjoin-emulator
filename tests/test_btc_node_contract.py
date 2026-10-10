"""Per-call RPC deadlines for the Bitcoin Core node."""

from collections.abc import Mapping
from unittest.mock import Mock, patch

from manager.btc_node import (
    RPC_TIMEOUT_SECONDS,
    WRITE_RPC_TIMEOUT_SECONDS,
    BtcNode,
)


def response(body: Mapping[str, object]) -> Mock:
    result = Mock()
    result.json.return_value = body
    return result


def node() -> BtcNode:
    return BtcNode(host="btc-node", port=18443)


def test_read_only_calls_keep_the_short_polling_deadline() -> None:
    with patch(
        "manager.btc_node.requests.post",
        return_value=response({"error": None, "result": 1014}),
    ) as post:
        node().get_block_count()

    assert post.call_args.kwargs["timeout"] == RPC_TIMEOUT_SECONDS


def test_flushing_the_datadir_uses_the_utxo_statistics_call() -> None:
    """gettxoutsetinfo is the RPC that forces bitcoind to flush its block index and chainstate."""
    with patch(
        "manager.btc_node.requests.post",
        return_value=response({"error": None, "result": {"height": 1200}}),
    ) as post:
        node().flush_state_to_disk()

    assert b'"gettxoutsetinfo"' in post.call_args.kwargs["data"].encode()
    assert b'"none"' in post.call_args.kwargs["data"].encode()
    assert post.call_args.kwargs["timeout"] == WRITE_RPC_TIMEOUT_SECONDS


def test_funding_a_address_waits_far_longer_than_a_poll() -> None:
    """`fund_distributor` issues 200 sequential sends with no retry above them.

    Coin selection can slow down as the funding wallet collects change, so the
    tail must not inherit the short readiness-poll deadline.
    """
    with patch(
        "manager.btc_node.requests.post",
        return_value=response({"error": None, "result": "txid"}),
    ) as post:
        node().fund_address("bcrt1qexample", 0.5)

    assert post.call_args.kwargs["timeout"] == WRITE_RPC_TIMEOUT_SECONDS
    assert WRITE_RPC_TIMEOUT_SECONDS > RPC_TIMEOUT_SECONDS


def test_mining_blocks_waits_far_longer_than_a_poll() -> None:
    with patch(
        "manager.btc_node.requests.post",
        side_effect=[
            response({"error": None, "result": "bcrt1qminer"}),
            response({"error": None, "result": ["hash"]}),
        ],
    ) as post:
        node().mine_block()

    generate = [
        call for call in post.call_args_list
        if b"generatetoaddress" in call.kwargs["data"].encode()
    ]
    assert generate, "expected a generatetoaddress call"
    assert generate[0].kwargs["timeout"] == WRITE_RPC_TIMEOUT_SECONDS


def test_mining_is_judged_by_the_hashes_generatetoaddress_returned() -> None:
    """The periodic miner in btc-node may add a block of its own meanwhile."""
    with patch(
        "manager.btc_node.requests.post",
        side_effect=[
            response({"error": None, "result": "bcrt1qminer"}),
            response({"error": None, "result": ["h101", "h102", "h103"]}),
        ],
    ) as post:
        assert node().mine_block(3) is True

    assert not any(b"getblockcount" in call.kwargs["data"].encode() for call in post.call_args_list)


def test_mining_fewer_blocks_than_requested_is_a_failure() -> None:
    with patch(
        "manager.btc_node.requests.post",
        side_effect=[
            response({"error": None, "result": "bcrt1qminer"}),
            response({"error": None, "result": ["h101"]}),
        ],
    ):
        assert node().mine_block(3) is False
