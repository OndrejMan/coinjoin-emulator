"""Pipeline-facing image and Bitcoin data runtime contracts."""

import types
from pathlib import Path
from unittest.mock import Mock, patch

from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.engine.engine_base import EngineBase


class RuntimeEngine(EngineBase):
    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig("test", 1, 1, "test", [WalletConfig(funds=[1])])


def args(**overrides: object) -> types.SimpleNamespace:
    values: dict[str, object] = {
        "image_prefix": "registry/",
        "force_rebuild": False,
        "btc_node_image": "",
        "joinmarket_client_server_image": "",
        "irc_server_image": "",
        "coinjoin_infrastructure_local_build": False,
        "btcFolder": "",
        "btc_node_arg": [],
        "proxy": "",
        "in_cluster": False,
        "control_ip": "localhost",
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def engine(run_args: types.SimpleNamespace, driver: Mock) -> RuntimeEngine:
    return RuntimeEngine(run_args, driver, "/logs")


def test_exact_image_override_is_pulled_and_used() -> None:
    driver = Mock()
    driver.has_image.return_value = False

    engine(args(btc_node_image="example/btc@sha256:abc"), driver).prepare_image("btc-node")

    driver.pull.assert_called_once_with("example/btc@sha256:abc")


def test_local_build_wins_over_a_remote_image() -> None:
    driver = Mock()

    engine(
        args(btc_node_image="example/btc:remote", coinjoin_infrastructure_local_build=True), driver
    ).prepare_image("btc-node")

    driver.build.assert_called_once_with("example/btc:remote", "./containers/btc-node")
    driver.has_image.assert_not_called()


@patch("manager.engine.engine_base.BtcNode")
def test_btc_folder_and_node_arguments_reach_the_driver(node_class: Mock, tmp_path: Path) -> None:
    driver = Mock()
    driver.run.return_value = ("node-ip", {18443: 18443, 18444: 18444}, None)

    engine(
        args(
            btcFolder=str(tmp_path),
            btc_node_arg=["-blocksxor=0", "-prune=0"],
            btc_node_image="example/btc:exact",
        ),
        driver,
    ).start_btc_node()

    call = driver.run.call_args
    assert call.args[:2] == ("btc-node", "example/btc:exact")
    assert call.kwargs["volumes"] == {str(tmp_path): {"bind": "/home/bitcoin/data", "mode": "rw"}}
    assert call.kwargs["command"] == ["./run.sh", "-blocksxor=0", "-prune=0"]
    node_class.return_value.wait_ready.assert_called_once_with()


def test_in_cluster_driver_uses_the_service_dns_name_and_service_port() -> None:
    driver = Mock(in_cluster=True)
    runtime = engine(args(in_cluster=False), driver)

    assert runtime.service_endpoint("btc-node.ns.svc", 37128, {37128: 37131}) == (
        "btc-node.ns.svc",
        37131,
    )


def test_a_local_run_reaches_the_control_host_on_the_published_port() -> None:
    runtime = engine(args(), Mock(in_cluster=False))

    assert runtime.service_endpoint("172.17.0.2", 28183, {28183: 28185}) == ("localhost", 28185)


def test_a_route_is_reached_over_https() -> None:
    runtime = engine(args(), Mock(in_cluster=False))

    assert runtime.service_endpoint("172.17.0.2", 28183, {}, "app.example.org") == (
        "app.example.org",
        443,
    )


def test_a_proxied_run_reaches_the_container_port_directly() -> None:
    runtime = engine(args(proxy="socks5://localhost:9050"), Mock(in_cluster=False))

    assert runtime.service_endpoint("172.17.0.2", 28183, {28183: 28185}) == ("172.17.0.2", 28183)


@patch("manager.engine.engine_base.BtcNode")
def test_a_shared_btc_folder_runs_the_node_as_the_storage_identity(
    node_class: Mock, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KUBERNETES_STORAGE_UID", "5001")
    monkeypatch.setenv("KUBERNETES_STORAGE_GID", "5002")
    driver = Mock()
    driver.run.return_value = ("node-ip", {18443: 18443, 18444: 18444}, None)

    engine(args(btcFolder=str(tmp_path)), driver).start_btc_node()

    assert driver.run.call_args.kwargs["run_as_user"] == 5001
    assert driver.run.call_args.kwargs["run_as_group"] == 5002


@patch("manager.engine.engine_base.BtcNode")
def test_the_node_keeps_its_image_identity_without_a_shared_folder(
    node_class: Mock, monkeypatch
) -> None:
    monkeypatch.setenv("KUBERNETES_STORAGE_UID", "5001")
    driver = Mock()
    driver.run.return_value = ("node-ip", {18443: 18443, 18444: 18444}, None)

    engine(args(), driver).start_btc_node()

    assert driver.run.call_args.kwargs["run_as_user"] is None


@patch("manager.engine.engine_base.BtcNode")
def test_the_btc_node_receives_the_requested_initial_block_count(
    node_class: Mock, monkeypatch
) -> None:
    monkeypatch.setenv("COINJOIN_BTC_NODE_INITIAL_BLOCK_COUNT", "201")
    driver = Mock()
    driver.run.return_value = ("node-ip", {18443: 18443, 18444: 18444}, None)

    engine(args(), driver).start_btc_node()

    assert driver.run.call_args.kwargs["env"] == {"COINJOIN_INITIAL_BLOCK_COUNT": "201"}
