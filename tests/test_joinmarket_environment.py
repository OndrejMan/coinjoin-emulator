from types import SimpleNamespace
from typing import cast

from manager.engine.engine_base import EngineArgs
from manager.engine.joinmarket import JOINMARKET_COUNTERPARTIES
from manager.engine.joinmarket import joinmarket_container_env as package_container_env
from manager.engine.joinmarket.environment import joinmarket_container_env


def joinmarket_args(fallback: bool = False) -> EngineArgs:
    return cast(
        EngineArgs,
        SimpleNamespace(joinmarket_descriptor_regtest_fallback=fallback),
    )


class TestJoinMarketEnvironment:
    def test_package_reexports_environment_and_constants(self) -> None:
        assert package_container_env is joinmarket_container_env
        assert JOINMARKET_COUNTERPARTIES == 4

    def test_container_env_encodes_descriptor_fallback_flag(self) -> None:
        assert joinmarket_container_env(joinmarket_args(), "wallet-a") == {
            "JM_RPC_WALLET_FILE": "wallet-a",
            "JM_DESCRIPTOR_REGTEST_FALLBACK": "0",
        }
        assert joinmarket_container_env(joinmarket_args(fallback=True), "wallet-b") == {
            "JM_RPC_WALLET_FILE": "wallet-b",
            "JM_DESCRIPTOR_REGTEST_FALLBACK": "1",
        }
