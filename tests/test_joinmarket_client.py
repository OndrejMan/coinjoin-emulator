import unittest

import manager.wasabi_clients.joinmarket as joinmarket_package
import manager.wasabi_clients.joinmarket_client as joinmarket_shim
from manager.wasabi_clients.joinmarket_client import JoinMarketClientServer


class JoinMarketClientServerTest(unittest.TestCase):
    def test_legacy_module_reexports_joinmarket_package_api(self) -> None:
        self.assertIs(joinmarket_shim.JoinMarketClientServer, joinmarket_package.JoinMarketClientServer)
        self.assertIs(joinmarket_shim.JoinmarketConflictException, joinmarket_package.JoinmarketConflictException)
        self.assertEqual(joinmarket_shim.WALLET_NAME, joinmarket_package.WALLET_NAME)
        self.assertEqual(joinmarket_shim.PASSWORD, joinmarket_package.PASSWORD)
        self.assertEqual(joinmarket_shim.WALLET_TYPE, joinmarket_package.WALLET_TYPE)
        self.assertEqual(joinmarket_shim.BTC, joinmarket_package.BTC)

    def test_type_property_keeps_role_compatibility(self) -> None:
        client = JoinMarketClientServer(host="dind", role="maker")

        self.assertEqual(client.role, "maker")
        self.assertEqual(client.type, "maker")

        client.type = "taker"

        self.assertEqual(client.role, "taker")
        self.assertEqual(client.type, "taker")


if __name__ == "__main__":
    unittest.main()
