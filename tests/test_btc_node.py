import json
import unittest
from unittest.mock import Mock, patch

import requests

from manager.btc_node import BtcNode
from manager.exceptions import RpcError

# pylint: disable=protected-access


def response(body: dict[str, object] | None = None, status_error: Exception | None = None) -> Mock:
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = status_error
    mock_response.json.return_value = body or {"error": None, "result": "ok"}
    mock_response.text = json.dumps(mock_response.json.return_value)
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

    def test_rpc_surfaces_json_error_body_from_http_500(self) -> None:
        node = BtcNode(host="btc-node", port=18443)
        body = {
            "error": {
                "code": -18,
                "message": "Requested wallet does not exist or is not loaded",
            },
            "result": None,
        }

        with patch(
            "manager.btc_node.requests.post",
            return_value=response(body, requests.exceptions.HTTPError("500 Server Error")),
        ):
            with self.assertRaises(RpcError) as error:
                node._rpc({"method": "sendtoaddress", "params": ["bcrt1address", 0.1]}, wallet="wallet")

        message = str(error.exception)
        self.assertIn("sendtoaddress", message)
        self.assertIn("wallet=wallet", message)
        self.assertIn("code=-18", message)
        self.assertIn("Requested wallet does not exist or is not loaded", message)

    def test_funding_wallet_ready_accepts_loaded_wallet(self) -> None:
        node = BtcNode(host="btc-node", port=18443)

        with patch.object(node, "_rpc", side_effect=[["wallet"], {"walletname": "wallet"}, True]) as rpc:
            node.ensure_funding_wallet_ready()

        self.assertEqual(rpc.call_count, 3)
        self.assertEqual(rpc.call_args_list[0].args[0]["method"], "listwallets")
        self.assertEqual(rpc.call_args_list[1].args[0]["method"], "getwalletinfo")
        self.assertEqual(rpc.call_args_list[1].args[1], "wallet")
        self.assertEqual(rpc.call_args_list[2].args[0]["method"], "settxfee")
        self.assertEqual(rpc.call_args_list[2].args[1], "wallet")

    def test_funding_wallet_ready_loads_existing_wallet(self) -> None:
        node = BtcNode(host="btc-node", port=18443)

        with patch.object(
            node,
            "_rpc",
            side_effect=[[], {"name": "wallet"}, {"walletname": "wallet"}, True],
        ) as rpc:
            node.ensure_funding_wallet_ready()

        self.assertEqual(rpc.call_count, 4)
        self.assertEqual(rpc.call_args_list[1].args[0]["method"], "loadwallet")
        self.assertEqual(rpc.call_args_list[1].args[0]["params"], ["wallet"])
        self.assertEqual(rpc.call_args_list[2].args[0]["method"], "getwalletinfo")
        self.assertEqual(rpc.call_args_list[3].args[0]["method"], "settxfee")

    def test_funding_wallet_ready_creates_missing_wallet(self) -> None:
        node = BtcNode(host="btc-node", port=18443)
        missing_wallet = RpcError(
            "Bitcoin Core RPC loadwallet failed: code=-18 "
            "message=Wallet file verification failed. Path does not exist"
        )

        with patch.object(node, "_rpc", side_effect=[[], missing_wallet, {"walletname": "wallet"}, True]) as rpc:
            with patch.object(node, "create_wallet") as create_wallet:
                node.ensure_funding_wallet_ready()

        create_wallet.assert_called_once_with("wallet")
        self.assertEqual(rpc.call_args_list[2].args[0]["method"], "getwalletinfo")
        self.assertEqual(rpc.call_args_list[2].args[1], "wallet")
        self.assertEqual(rpc.call_args_list[3].args[0]["method"], "settxfee")
        self.assertEqual(rpc.call_args_list[3].args[1], "wallet")


if __name__ == "__main__":
    unittest.main()
