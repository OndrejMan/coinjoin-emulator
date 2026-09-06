"""JoinMarket Core wallet setup contract."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.engine.joinmarket_engine import JoinmarketEngine


def engine() -> JoinmarketEngine:
    instance = object.__new__(JoinmarketEngine)
    instance.args = SimpleNamespace()
    return instance


def test_core_wallet_names_are_unique() -> None:
    assert JoinmarketEngine.core_wallet_name("jcs-001") == "jm_wallet_jcs-001"
    assert JoinmarketEngine.core_wallet_name("joinmarket-distributor") == "jm_wallet_joinmarket-distributor"


def test_container_environment_selects_the_watch_only_wallet() -> None:
    assert engine().joinmarket_container_env("jm_wallet_jcs_001") == {
        "JM_RPC_WALLET_FILE": "jm_wallet_jcs_001",
    }


def test_local_build_creates_the_vendored_base_before_the_client(monkeypatch) -> None:
    instance = engine()
    instance.args = SimpleNamespace(image_prefix="registry/")
    instance.driver = Mock()
    instance.local_build_requested = Mock(return_value=True)
    calls = []
    instance.prepare_image = Mock(side_effect=calls.append)
    instance.driver.build.side_effect = lambda image, path: calls.append((image, path))
    monkeypatch.setattr(
        "manager.engine.joinmarket_engine.os.path.isdir",
        lambda path: path == "./vendor/joinmarket-clientserver",
    )

    instance.prepare_images()

    assert calls == [
        "btc-node",
        ("registry/joinmarket-base:latest", "./vendor/joinmarket-clientserver"),
        "joinmarket-client-server",
        "irc-server",
    ]


def test_core_wallet_creation_does_not_import_funding_descriptors() -> None:
    instance = engine()
    instance.node = Mock()
    instance._core_wallet_lock = threading.Lock()  # pylint: disable=protected-access
    assert instance.create_core_wallet("jcs-002") == "jm_wallet_jcs-002"
    assert instance.node.mock_calls == [
        call.create_wallet("jm_wallet_jcs-002", disable_private_keys=True),
    ]


class RoleClient:
    def __init__(self, role: str) -> None:
        self.name = role
        self.type = role

    def get_balance(self) -> int:
        return 0


def role_engine(*roles: str) -> JoinmarketEngine:
    instance = engine()
    instance.clients = [RoleClient(role) for role in roles]
    instance.scenario = ScenarioConfig(
        "roles", 1, 1, "joinmarket", [WalletConfig(funds=[1]) for _ in roles]
    )
    return instance


def test_a_joinmarket_run_requires_a_started_maker_and_taker() -> None:
    with pytest.raises(RuntimeError, match="taker"):
        role_engine("maker").validate_clients()
    with pytest.raises(RuntimeError, match="maker"):
        role_engine("taker").validate_clients()

    role_engine("maker", "taker").validate_clients()
