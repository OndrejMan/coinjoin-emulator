import json
import unittest
from unittest.mock import Mock, patch

from manager.btc_node import BtcNode

# pylint: disable=protected-access


def response(body: dict[str, object] | None = None) -> Mock:
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = body or {"error": None, "result": "ok"}
    return mock_response


class BtcNodeTest(unittest.TestCase):
    def test_rpc_uses_requested_wallet_name(self) -> None:
        node = BtcNode(host="btc-node", port=18443)

        with patch("manager.btc_node.requests.post", return_value=response()) as post:
            result = node._rpc({"method": "getwalletinfo", "params": []}, wallet="jm_wallet_jcs_000")

        self.assertEqual(result, "ok")
        self.assertEqual(
            post.call_args.args[0],
            "http://btc-node:18443/wallet/jm_wallet_jcs_000",
        )
        request = json.loads(post.call_args.kwargs["data"])
        self.assertEqual(request["method"], "getwalletinfo")


if __name__ == "__main__":
    unittest.main()
