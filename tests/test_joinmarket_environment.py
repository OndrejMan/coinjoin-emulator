"""JoinMarket Core wallet setup contract."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock, call

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


def test_core_wallet_creation_does_not_import_funding_descriptors() -> None:
    instance = engine()
    instance.node = Mock()
    instance._core_wallet_lock = threading.Lock()  # pylint: disable=protected-access
    assert instance.create_core_wallet("jcs-002") == "jm_wallet_jcs-002"
    assert instance.node.mock_calls == [
        call.create_wallet("jm_wallet_jcs-002", disable_private_keys=True),
    ]
