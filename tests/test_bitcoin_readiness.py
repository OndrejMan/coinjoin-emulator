"""Bitcoin Core startup-readiness policy tests."""

from unittest.mock import Mock, patch

import pytest

from manager.bitcoin_readiness import wait_for_fee_history, wait_for_node_ready


def readiness_node() -> Mock:
    node = Mock()
    node.host = "btc-node"
    node.port = 18443
    return node


def test_wait_for_node_ready_requires_a_fully_synchronized_chain() -> None:
    node = readiness_node()
    still_syncing = {"headers": 202, "initialblockdownload": True, "verificationprogress": 0.99}
    synchronized = {"headers": 201, "initialblockdownload": False, "verificationprogress": 1.0}
    node.get_block_count.side_effect = [201, 201]
    node.get_blockchain_info.side_effect = [still_syncing, synchronized]

    with (
        patch("manager.bitcoin_readiness.monotonic", side_effect=[0.0, 1.0, 2.0, 3.0]),
        patch("manager.bitcoin_readiness.sleep") as sleep,
        patch("manager.bitcoin_readiness.wait_for_fee_history") as wait_for_fee_history_mock,
    ):
        wait_for_node_ready(node, timeout=10)

    node.ensure_funding_wallet_ready.assert_called_once_with()
    wait_for_fee_history_mock.assert_called_once_with(node, 7.0)
    sleep.assert_called_once_with(1)


def test_wait_for_node_ready_has_a_deadline() -> None:
    node = readiness_node()

    with patch("manager.bitcoin_readiness.monotonic", side_effect=[0.0, 11.0]):
        with pytest.raises(TimeoutError, match="was not ready after 10s"):
            wait_for_node_ready(node, timeout=10)


def test_wait_for_fee_history_requires_a_fee_estimate_and_quiet_chain_tip() -> None:
    node = readiness_node()
    synchronized = {"blocks": 201, "headers": 201, "initialblockdownload": False, "verificationprogress": 1.0}
    node.estimate_smart_fee.return_value = {"feerate": 0.0001}
    node.get_blockchain_info.return_value = synchronized

    with (
        patch("manager.bitcoin_readiness.monotonic", side_effect=range(8)),
        patch("manager.bitcoin_readiness.sleep") as sleep,
    ):
        wait_for_fee_history(node, timeout=10)

    node.estimate_smart_fee.assert_called_once_with()
    assert node.get_blockchain_info.call_count == 6
    assert sleep.call_count == 5
