"""Coordinator startup: a known transient failure must not lose the whole run."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from manager.engine.wasabi_engine import WasabiEngine, coordinator_retry_reason
from manager.wasabi_backend_factory import BackendArchitecture


def engine() -> WasabiEngine:
    instance = object.__new__(WasabiEngine)
    instance.args = SimpleNamespace(image_prefix="", btc_node_ip="", proxy="", in_cluster=False, control_ip="localhost")
    instance.backend_architecture = BackendArchitecture.SPLIT
    instance.node = SimpleNamespace(internal_ip="10.0.0.2")
    instance.driver = Mock()
    instance.driver.run.return_value = ("wasabi-coordinator", {37128: 37128}, None)
    instance.versions = {"2.6.0"}
    instance.scenario = SimpleNamespace(backend=None)
    return instance


def test_a_transient_startup_failure_is_recognized() -> None:
    assert coordinator_retry_reason("Bitcoin Node is not fully synchronized") is not None
    assert coordinator_retry_reason("System.Net.Sockets: address already in use") is not None
    assert coordinator_retry_reason("Unhandled configuration error") is None


def test_the_coordinator_is_restarted_after_a_transient_failure() -> None:
    instance = engine()
    instance.driver.logs.return_value = "Bitcoin Node is not fully synchronized"
    coordinator = Mock()
    coordinator.wait_ready.side_effect = [TimeoutError("not ready"), None]

    with (
        patch("manager.engine.wasabi_engine.create_coordinator", return_value=coordinator),
        patch("manager.engine.wasabi_engine.sleep"),
    ):
        instance.start_wasabi_coordinator()

    instance.driver.stop.assert_called_once_with("wasabi-coordinator")
    assert instance.driver.run.call_count == 2
    assert instance.driver.upload.call_count == 2


def test_an_unknown_startup_failure_fails_the_run_with_the_logs() -> None:
    instance = engine()
    instance.driver.logs.return_value = "Unhandled configuration error"
    coordinator = Mock()
    coordinator.wait_ready.side_effect = TimeoutError("not ready")

    with (
        patch("manager.engine.wasabi_engine.create_coordinator", return_value=coordinator),
        patch("manager.engine.wasabi_engine.sleep"),
    ):
        with pytest.raises(Exception, match="Unhandled configuration error"):
            instance.start_wasabi_coordinator()

    instance.driver.stop.assert_not_called()


def test_the_coordinator_config_carries_the_scenario_backend_overrides() -> None:
    instance = engine()
    instance.scenario = SimpleNamespace(backend={"MiningFeeRate": 5})

    instance.upload_coordinator_config("2.6.0")

    name, source, destination = instance.driver.upload.call_args.args
    assert name == "wasabi-coordinator"
    assert destination == "/home/wasabi/.walletwasabi/coordinator/Config.json"
    with open(source, encoding="utf-8") as config_file:
        config = json.load(config_file)
    assert config["MiningFeeRate"] == 5
    assert config["BitcoinCoreRpcEndPoint"] == "10.0.0.2:18443"


def test_the_split_distributor_is_pointed_at_the_coordinator() -> None:
    instance = engine()
    instance.backend = SimpleNamespace(internal_ip="10.0.0.3")
    instance.coordinator = SimpleNamespace(internal_ip="10.0.0.4")
    instance.args.wasabi_backend_ip = ""
    instance.scenario = SimpleNamespace(distributor_version=None, default_version="2.6.0")
    instance.driver.run.return_value = ("wasabi-client-distributor", {37128: 37131}, None)
    distributor = Mock()
    distributor.wait_wallet.return_value = True
    instance.init_wasabi_client = Mock(return_value=distributor)
    instance.args.distributor_startup_timeout = 60

    instance.start_distributor()

    assert instance.driver.run.call_args.kwargs["env"]["ADDR_WASABI_COORDINATOR"] == "10.0.0.4"
