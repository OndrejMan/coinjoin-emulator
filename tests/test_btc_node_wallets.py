"""Bitcoin Core wallet handling required by the JoinMarket clients."""

from collections.abc import Mapping
from unittest.mock import Mock, patch

from manager.btc_node import BtcNode


def response(body: Mapping[str, object]) -> Mock:
    result = Mock()
    result.json.return_value = body
    return result


def test_rpc_uses_the_requested_wallet_path() -> None:
    node = BtcNode(host="btc-node", port=18443)

    with patch(
        "manager.btc_node.requests.post",
        return_value=response({"error": None, "result": {"walletname": "unique"}}),
    ) as post:
        node._rpc({"method": "getwalletinfo", "params": []}, "jm_wallet_jcs_001")  # pylint: disable=protected-access

    assert post.call_args.args[0].endswith("/wallet/jm_wallet_jcs_001")


def test_create_wallet_falls_back_to_descriptors_without_private_keys() -> None:
    bdb_error = {"error": {"code": -4, "message": "BDB wallet creation is deprecated"}}
    created = {"result": {"name": "jm_wallet_jcs_000"}, "error": None}
    node = BtcNode()

    with patch(
        "manager.btc_node.requests.post", side_effect=[response(bdb_error), response(created)]
    ) as post:
        node.create_wallet("jm_wallet_jcs_000", disable_private_keys=True)

    assert '"descriptors": false' in post.call_args_list[0].kwargs["data"]
    assert '"descriptors": true' in post.call_args_list[1].kwargs["data"]
    assert '"disable_private_keys": true' in post.call_args_list[1].kwargs["data"]


def test_create_wallet_loads_a_wallet_left_behind_by_an_earlier_run() -> None:
    exists = {"error": {"code": -4, "message": "Database already exists."}}
    node = BtcNode()

    with patch("manager.btc_node.requests.post", return_value=response(exists)) as post:
        with patch.object(BtcNode, "_rpc") as rpc:
            node.create_wallet("jm_wallet_jcs_000")

    assert post.call_count == 1
    assert [call.args[0]["method"] for call in rpc.call_args_list] == ["loadwallet", "getwalletinfo"]
