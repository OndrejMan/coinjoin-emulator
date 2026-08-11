"""JoinMarket container isolation contract."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from manager.engine.base.clients import EngineClientsMixin
from manager.engine.base.protocols import EmulatorClient, EngineArgs
from manager.engine.configuration import ScenarioConfig, WalletConfig
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


def test_orderbook_entrypoint_exits_instead_of_starting_walletd() -> None:
    entrypoint = (
        Path(__file__).resolve().parents[1]
        / "containers"
        / "joinmarket-client-server"
        / "run.sh"
    ).read_text(encoding="utf-8")
    obwatch_branch = entrypoint.split('if [ "${MODE}" = "obwatch" ]; then', 1)[1].split(
        "fi", 1
    )[0]

    assert "blockchain_source = no-blockchain" in obwatch_branch
    assert 'exit "${PIPESTATUS[0]}"' in obwatch_branch


class RoleClient:
    def __init__(self, role: str) -> None:
        self.name = role
        self.type = role

    def get_status(self) -> dict[str, bool]:
        return {"wallet": True}

    def wait_wallet(self, timeout: int | None) -> bool:
        return True

    def get_balance(self) -> int:
        return 0


class LifecycleHarness(JoinMarketLifecycleMixin, EngineClientsMixin):
    def __init__(self, *roles: str) -> None:
        self.clients = [cast(EmulatorClient, RoleClient(role)) for role in roles]
        self.scenario = ScenarioConfig(
            "roles",
            1,
            1,
            "joinmarket",
            [WalletConfig(funds=[1]) for _ in roles],
        )


def test_joinmarket_requires_a_started_maker_and_taker() -> None:
    with pytest.raises(RuntimeError, match="taker"):
        LifecycleHarness("maker").validate_clients()

    LifecycleHarness("maker", "taker").validate_clients()
