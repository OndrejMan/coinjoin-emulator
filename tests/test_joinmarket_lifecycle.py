from manager.engine.joinmarket.lifecycle import JoinMarketClientLifecycleMixin


class TestJoinMarketLifecycle:
    def test_core_wallet_name_is_valid_for_bitcoin_core(self) -> None:
        lifecycle = JoinMarketClientLifecycleMixin()

        assert lifecycle.core_wallet_name("jcs-001") == "jm_wallet_jcs_001"
        assert lifecycle.core_wallet_name("joinmarket-distributor") == "jm_wallet_joinmarket_distributor"
