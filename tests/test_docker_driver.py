"""Docker driver contracts for endpoint resolution and artifact collection."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from manager.driver.docker import DockerDriver


def driver() -> DockerDriver:
    instance = object.__new__(DockerDriver)
    instance.client = Mock()
    instance._namespace = "coinjoin"  # pylint: disable=protected-access
    instance.__dict__["network"] = SimpleNamespace(id="net-1")
    return instance


def test_containers_are_addressed_by_name_on_the_bridge_network() -> None:
    instance = driver()

    endpoint = instance.run("jcs-000", "jcs:latest", ports={28183: 28185}, cpu=0.1, memory=64)

    assert endpoint == ("jcs-000", {28183: 28185}, None)


def test_a_failed_download_is_reported_instead_of_ignored() -> None:
    import docker

    instance = driver()
    instance.client.containers.get.side_effect = docker.errors.NotFound("no such container")

    with pytest.raises(RuntimeError, match="Failed to download jcs-000:/logs"):
        instance.download("jcs-000", "/logs", "/tmp/out")


def test_a_running_container_is_paused_while_it_is_archived(tmp_path) -> None:
    instance = driver()
    container = instance.client.containers.get.return_value
    container.status = "running"
    container.get_archive.return_value = (iter([tar_bytes()]), {})

    instance.download("jcs-000", "/logs", str(tmp_path))

    container.pause.assert_called_once_with()
    container.unpause.assert_called_once_with()


def tar_bytes() -> bytes:
    import io
    import tarfile

    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as tar:
        info = tarfile.TarInfo("logs")
        info.type = tarfile.DIRTYPE
        tar.addfile(info)
    return payload.getvalue()


def test_stopped_containers_are_still_found_during_cleanup() -> None:
    instance = driver()
    instance.client.containers.list.return_value = []
    instance.client.networks.list.return_value = []

    instance.cleanup()

    assert instance.client.containers.list.call_args.kwargs == {"all": True}
