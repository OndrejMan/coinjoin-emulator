"""Pipeline-facing image and Bitcoin data runtime contracts."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from manager.driver import Driver
from manager.engine.base.protocols import EngineArgs
from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.engine.engine_base import EngineBase


class RuntimeEngine(EngineBase):
    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig("test", 1, 1, "test", [WalletConfig(funds=[1])])


def args(**overrides: object) -> SimpleNamespace:
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
    return SimpleNamespace(**values)


def engine(run_args: SimpleNamespace, driver: Mock) -> RuntimeEngine:
    return RuntimeEngine(cast(EngineArgs, run_args), cast(Driver, driver), "/logs")


def test_exact_image_override_is_pulled_and_used() -> None:
    driver = Mock()
    driver.has_image.return_value = False
    runtime = engine(args(btc_node_image="example/btc@sha256:abc"), driver)

    runtime.prepare_image("btc-node")

    driver.pull.assert_called_once_with("example/btc@sha256:abc")


def test_local_build_wins_over_remote_image() -> None:
    driver = Mock()
    runtime = engine(
        args(
            btc_node_image="example/btc:remote",
            coinjoin_infrastructure_local_build=True,
        ),
        driver,
    )

    runtime.prepare_image("btc-node")

    driver.build.assert_called_once_with("example/btc:remote", "./containers/btc-node")
    driver.has_image.assert_not_called()


@patch("manager.engine.engine_base.BtcNode")
def test_btc_folder_and_node_arguments_reach_driver(node_class: Mock, tmp_path: object) -> None:
    driver = Mock()
    driver.run.return_value = ("node-ip", {18443: 18443, 18444: 18444}, None)
    runtime_args = args(
        btcFolder=str(tmp_path),
        btc_node_arg=["-blocksxor=0", "-prune=0"],
        btc_node_image="example/btc:exact",
    )

    engine(runtime_args, driver).start_btc_node()

    driver.run.assert_called_once()
    call = driver.run.call_args
    assert call.args[:2] == ("btc-node", "example/btc:exact")
    assert call.kwargs["volumes"] == {
        str(tmp_path): {"bind": "/home/bitcoin/data", "mode": "rw"}
    }
    assert call.kwargs["command"] == ["./run.sh", "-blocksxor=0", "-prune=0"]
    node_class.return_value.wait_ready.assert_called_once_with()
