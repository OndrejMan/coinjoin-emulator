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
