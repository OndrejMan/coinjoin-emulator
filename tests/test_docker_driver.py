"""Docker artifact-transfer failure semantics."""

from typing import cast
from unittest.mock import Mock

import docker
import pytest

from manager.driver.docker import DockerDriver


def test_run_uses_network_dns_name_instead_of_legacy_ip_field() -> None:
    driver = object.__new__(DockerDriver)
    client = Mock()
    client.networks.create.return_value.id = "network-id"
    client.containers.run.return_value.attrs = {"NetworkSettings": {}}
    driver.client = cast(docker.DockerClient, client)
    driver._namespace = "coinjoin"  # pylint: disable=protected-access

    host, ports, route = driver.run(
        "wasabi-client-distributor",
        "example/wasabi-client:local",
        ports={37128: 37131},
    )

    assert host == "wasabi-client-distributor"
    assert ports == {37128: 37131}
    assert route is None


def test_download_surfaces_missing_container() -> None:
    driver = object.__new__(DockerDriver)
    client = Mock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    driver.client = cast(docker.DockerClient, client)

    with pytest.raises(RuntimeError, match="Failed to download btc-node"):
        driver.download("btc-node", "/home/bitcoin/data", "/tmp/output")
