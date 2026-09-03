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
