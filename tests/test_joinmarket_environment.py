"""JoinMarket container isolation contract."""

from types import SimpleNamespace
from typing import cast

from manager.engine.base.protocols import EngineArgs
from manager.engine.joinmarket.environment import joinmarket_container_env
from manager.engine.joinmarket.lifecycle import JoinMarketLifecycleMixin


def test_core_wallet_names_are_unique_and_core_safe() -> None:
    lifecycle = JoinMarketLifecycleMixin()

    assert lifecycle.core_wallet_name("jcs-001") == "jm_wallet_jcs_001"
    assert lifecycle.core_wallet_name("joinmarket-distributor") == "jm_wallet_joinmarket_distributor"


def test_container_environment_selects_wallet_and_descriptor_fallback() -> None:
    args = cast(
        EngineArgs,
        SimpleNamespace(joinmarket_descriptor_regtest_fallback=True),
    )

    assert joinmarket_container_env(args, "jm_wallet_jcs_001") == {
        "JM_RPC_WALLET_FILE": "jm_wallet_jcs_001",
        "JM_DESCRIPTOR_REGTEST_FALLBACK": "1",
    }
