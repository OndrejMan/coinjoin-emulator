"""Docker artifact-transfer failure semantics."""

import tarfile
from io import BytesIO
from typing import cast
from unittest.mock import Mock

import docker
import pytest

from manager.driver import RESERVED_PORT_RANGE, RESERVED_PORTS_SYSCTL
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
    assert client.containers.run.call_args.kwargs["auto_remove"] is False
    assert client.containers.run.call_args.kwargs["sysctls"] == {
        RESERVED_PORTS_SYSCTL: RESERVED_PORT_RANGE
    }


def test_stop_removes_container_after_preserving_it_for_diagnostics() -> None:
    driver = object.__new__(DockerDriver)
    client = Mock()
    container = client.containers.get.return_value
    driver.client = cast(docker.DockerClient, client)

    driver.stop("failed-client")

    container.stop.assert_called_once_with()
    container.remove.assert_called_once_with(force=True, v=True)


def test_logs_decode_container_output() -> None:
    driver = object.__new__(DockerDriver)
    client = Mock()
    client.containers.get.return_value.logs.return_value = b"address already in use\n"
    driver.client = cast(docker.DockerClient, client)

    assert driver.logs("wasabi-coordinator") == "address already in use\n"


def test_download_surfaces_missing_container() -> None:
    driver = object.__new__(DockerDriver)
    client = Mock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    driver.client = cast(docker.DockerClient, client)

    with pytest.raises(RuntimeError, match="Failed to download btc-node"):
        driver.download("btc-node", "/home/bitcoin/data", "/tmp/output")


def test_download_pauses_a_running_container_while_archiving(tmp_path: object) -> None:
    driver = object.__new__(DockerDriver)
    client = Mock()
    container = client.containers.get.return_value
    container.status = "running"
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        info = tarfile.TarInfo("client.log")
        content = b"stable log\n"
        info.size = len(content)
        stream.addfile(info, BytesIO(content))
    container.get_archive.return_value = ([archive.getvalue()], {})
    driver.client = cast(docker.DockerClient, client)

    driver.download("client", "/logs", str(tmp_path))

    container.pause.assert_called_once_with()
    container.unpause.assert_called_once_with()


def test_download_unpauses_after_archive_failure(tmp_path: object) -> None:
    driver = object.__new__(DockerDriver)
    client = Mock()
    container = client.containers.get.return_value
    container.status = "running"
    container.get_archive.side_effect = docker.errors.APIError("broken archive")
    driver.client = cast(docker.DockerClient, client)

    with pytest.raises(RuntimeError, match="Failed to download"):
        driver.download("client", "/logs", str(tmp_path))

    container.pause.assert_called_once_with()
    container.unpause.assert_called_once_with()
