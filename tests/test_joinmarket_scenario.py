from manager.engine.configuration import JoinMarketRole
from manager.engine.joinmarket.scenario import default_joinmarket_scenario


class TestJoinMarketScenario:
    def test_default_scenario_factory_returns_independent_config(self) -> None:
        first = default_joinmarket_scenario()
        second = default_joinmarket_scenario()

        first.wallets.pop()

        assert first.default_version == "joinmarket"
        assert second.default_version == "joinmarket"
        assert len(second.wallets) == 12
        assert sum(
            wallet.joinmarket is not None and wallet.joinmarket.role == JoinMarketRole.TAKER
            for wallet in second.wallets
        ) == 2
        assert sum(
            wallet.joinmarket is not None and wallet.joinmarket.role == JoinMarketRole.MAKER
            for wallet in second.wallets
        ) == 10
