"""How a started JoinMarket client is addressed back from the manager."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from manager.driver import Driver
from manager.engine.base.protocols import EngineArgs
from manager.engine.configuration import JoinMarketConfig, JoinMarketRole, ScenarioConfig, WalletConfig
from manager.engine.engine_base import EngineBase
from manager.engine.joinmarket.lifecycle import JoinMarketLifecycleMixin


class EndpointEngine(JoinMarketLifecycleMixin, EngineBase):
    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig("test", 1, 1, "joinmarket", [WalletConfig(funds=[1])])


def args(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "image_prefix": "registry/",
        "joinmarket_client_server_image": "",
        "joinmarket_descriptor_regtest_fallback": False,
        "proxy": "",
        "in_cluster": False,
        "control_ip": "10.0.0.5",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def start_client(driver_ports: dict[int, int], **arg_overrides: object) -> dict[str, object]:
    """Start one client against a driver returning ``driver_ports`` and report the endpoint used."""
    driver = Mock()
    driver.in_cluster = bool(arg_overrides.get("in_cluster", False))
    driver.run.return_value = ("10.42.0.7", driver_ports, None)
    engine = EndpointEngine(cast(EngineArgs, args(**arg_overrides)), cast(Driver, driver), "/logs")
    wallet = WalletConfig(
        funds=[100_000],
        joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER, offers=[]),
    )

    with patch.object(EndpointEngine, "_create_joinmarket_core_wallet"), \
            patch("manager.engine.joinmarket.lifecycle.sleep"), \
            patch("manager.engine.joinmarket.lifecycle.client_from_wallet") as factory:
        engine.start_client(1, wallet)

    return dict(factory.call_args.kwargs)


def test_kubernetes_client_is_reached_on_the_allocated_node_port() -> None:
    # The driver allocates the NodePort; the 28184+idx rotation the manager asked
    # for only ever exists on a local docker host, so trusting it here would send
    # every wallet call to a closed port on the cluster node.
    call = start_client({28183: 30512})

    assert call["host"] == "10.0.0.5"
    assert call["port"] == 30512


def test_local_client_keeps_the_requested_port_rotation() -> None:
    # docker and podman echo the requested mapping back unchanged.
    call = start_client({28183: 28185})

    assert call["port"] == 28185


def test_in_cluster_client_is_reached_on_the_container_port() -> None:
    call = start_client({28183: 28185}, in_cluster=True)

    assert call["host"] == "10.42.0.7"
    assert call["port"] == 28183


def test_missing_driver_mapping_falls_back_to_the_requested_port() -> None:
    call = start_client({})

    assert call["port"] == 28185
