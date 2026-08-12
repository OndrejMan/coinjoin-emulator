"""Bitcoin Core wallet creation compatibility required by JoinMarket clients."""

from collections.abc import Mapping
from unittest.mock import Mock, patch

import pytest

from manager.btc_node import BtcNode


def response(body: Mapping[str, object]) -> Mock:
    result = Mock()
    result.json.return_value = body
    return result


def test_create_wallet_falls_back_to_descriptors_without_private_keys() -> None:
    bdb_error = {
        "error": {"code": -4, "message": "BDB wallet creation is deprecated"},
        "result": None,
    }
    created = {"error": None, "result": {"name": "jm_wallet_jcs_000"}}
    node = BtcNode()

    with patch("manager.btc_node.requests.post", side_effect=[response(bdb_error), response(created)]) as post:
        node.create_wallet("jm_wallet_jcs_000", disable_private_keys=True)

    first_request = post.call_args_list[0].kwargs["data"]
    second_request = post.call_args_list[1].kwargs["data"]
    assert '"descriptors": false' in first_request
    assert '"descriptors": true' in second_request
    assert '"disable_private_keys": true' in second_request


def test_rpc_uses_the_requested_wallet_path() -> None:
    node = BtcNode(host="btc-node", port=18443)
    with patch(
        "manager.btc_node.requests.post",
        return_value=response({"error": None, "result": {"walletname": "unique"}}),
    ) as post:
        node._rpc({"method": "getwalletinfo", "params": []}, "jm_wallet_jcs_001")  # pylint: disable=protected-access

    assert post.call_args.args[0].endswith("/wallet/jm_wallet_jcs_001")


def test_wait_ready_requires_a_fully_synchronized_chain() -> None:
    node = BtcNode()
    synchronized = {
        "headers": 201,
        "initialblockdownload": False,
        "verificationprogress": 1.0,
    }

    with (
        patch("manager.btc_node.monotonic", side_effect=[0.0, 1.0, 2.0]),
        patch.object(node, "get_block_count", return_value=201),
        patch.object(node, "get_blockchain_info", return_value=synchronized),
        patch.object(node, "ensure_funding_wallet_ready") as ensure_wallet,
        patch.object(node, "wait_fee_building_complete") as wait_fees,
    ):
        node.wait_ready(timeout=10)

    ensure_wallet.assert_called_once_with()
    wait_fees.assert_called_once_with(8.0)


def test_wait_ready_has_a_deadline() -> None:
    node = BtcNode(host="unreachable")

    with patch("manager.btc_node.monotonic", side_effect=[0.0, 11.0]):
        with pytest.raises(TimeoutError, match="was not ready after 10s"):
            node.wait_ready(timeout=10)
