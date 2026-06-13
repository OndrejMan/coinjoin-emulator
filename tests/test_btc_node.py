import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from manager.btc_node import BtcNode


class BtcNodeTest(unittest.TestCase):
    def test_create_wallet_retries_with_descriptors_when_bdb_is_deprecated(self):
        legacy_response = Mock()
        legacy_response.json.return_value = {
            "error": {
                "code": -4,
                "message": (
                    "BDB wallet creation is deprecated and will be removed in a future release. "
                    "In this release it can be re-enabled temporarily with the "
                    "-deprecatedrpc=create_bdb setting."
                ),
            }
        }

        descriptor_response = Mock()
        descriptor_response.json.return_value = {"error": None, "result": {"name": "jm_wallet"}}

        with patch("manager.btc_node.requests.post", side_effect=[legacy_response, descriptor_response]) as post:
            BtcNode().create_wallet("jm_wallet")

        first_request = json.loads(post.call_args_list[0].kwargs["data"])
        second_request = json.loads(post.call_args_list[1].kwargs["data"])
        self.assertFalse(first_request["params"]["descriptors"])
        self.assertTrue(second_request["params"]["descriptors"])
        self.assertEqual(second_request["params"]["wallet_name"], "jm_wallet")

    def test_create_wallet_retries_with_descriptors_when_bdb_is_unavailable(self):
        legacy_response = Mock()
        legacy_response.json.return_value = {
            "error": {
                "code": -4,
                "message": "Compiled without bdb support (required for legacy wallets)",
            }
        }

        descriptor_response = Mock()
        descriptor_response.json.return_value = {"error": None, "result": {"name": "jm_wallet"}}

        with patch("manager.btc_node.requests.post", side_effect=[legacy_response, descriptor_response]) as post:
            BtcNode().create_wallet("jm_wallet")

        first_request = json.loads(post.call_args_list[0].kwargs["data"])
        second_request = json.loads(post.call_args_list[1].kwargs["data"])
        self.assertFalse(first_request["params"]["descriptors"])
        self.assertTrue(second_request["params"]["descriptors"])
        self.assertEqual(second_request["params"]["wallet_name"], "jm_wallet")


if __name__ == "__main__":
    unittest.main()
