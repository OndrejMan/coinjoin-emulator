import unittest

from manager.engine.configuration import JoinMarketRole
from manager.engine.joinmarket_engine import JoinmarketEngine


class DefaultJoinMarketScenarioTest(unittest.TestCase):
    def test_default_joinmarket_scenario_has_surplus_makers_and_rounds(self) -> None:
        engine = object.__new__(JoinmarketEngine)
        scenario = engine.default_scenario()
        wallets = scenario.wallets
        takers = [
            wallet
            for wallet in wallets
            if wallet.joinmarket is not None
            and wallet.joinmarket.role == JoinMarketRole.TAKER
        ]
        makers = [
            wallet
            for wallet in wallets
            if wallet.joinmarket is not None
            and wallet.joinmarket.role == JoinMarketRole.MAKER
        ]

        self.assertGreaterEqual(scenario.rounds, 3)
        self.assertEqual(scenario.blocks, 0)
        self.assertEqual(scenario.default_version, "joinmarket")
        self.assertGreaterEqual(len(takers), 2)
        self.assertGreaterEqual(len(makers), 8)
        for maker in makers:
            fund_values = [
                fund if isinstance(fund, int) else fund.value
                for fund in maker.funds
            ]
            self.assertGreaterEqual(max(fund_values), 30000)


if __name__ == "__main__":
    unittest.main()
