"""Podman driver contracts against the pinned Python SDK."""

import tarfile
from io import BytesIO
from unittest.mock import Mock, patch

import podman
import pytest
import requests
from podman.domain.containers import Container
from podman.domain.containers_manager import ContainersManager

from manager.driver import managed_label_filters, managed_labels
from manager.driver.podman import PodmanDriver
from manager.exceptions import CoinjoinEmulatorError


@pytest.fixture
def driver_and_client():
    with patch("manager.driver.podman.podman.PodmanClient") as client_class:
        yield PodmanDriver(), client_class.return_value


def test_build_forwards_dockerfile_build_arguments(driver_and_client) -> None:
    driver, client = driver_and_client
    driver.build(
        "joinmarket-client-server",
        "/source",
        build_args={"JOINMARKET_BASE_IMAGE": "registry/joinmarket-base:latest"},
    )

    client.images.build.assert_called_once_with(
        path="/source",
        tag="joinmarket-client-server",
        rm=True,
        nocache=True,
        buildargs={"JOINMARKET_BASE_IMAGE": "registry/joinmarket-base:latest"},
    )


def test_image_queries_use_the_podman_client_only(driver_and_client) -> None:
    driver, client = driver_and_client
    client.images.get.side_effect = [None, podman.errors.ImageNotFound("missing")]

    assert driver.has_image("present") is True
    assert driver.has_image("missing") is False


def test_artifact_transfer_uses_the_podman_archive_api(driver_and_client, tmp_path) -> None:
    driver, client = driver_and_client
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        content = b"backend log"
        entry = tarfile.TarInfo("backend.log")
        entry.size = len(content)
        tar.addfile(entry, BytesIO(content))

    container = Mock()
    container.get_archive.return_value = ([archive.getvalue()], {})
    container.put_archive.return_value = True
    client.containers.get.return_value = container
    source = tmp_path / "scenario.json"
    source.write_text("{}")
    destination = tmp_path / "download"
    destination.mkdir()
    driver.download("btc-node", "/var/log/backend", str(destination))
    driver.upload("client", str(source), "/app/scenario.json")

    assert (destination / "backend.log").read_text() == "backend log"
    container.get_archive.assert_called_once_with("/var/log/backend")
    upload_path, upload_data = container.put_archive.call_args.args
    assert upload_path == "/app"
    assert upload_data


def test_failed_artifact_upload_raises(driver_and_client, tmp_path) -> None:
    driver, client = driver_and_client
    source = tmp_path / "scenario.json"
    source.write_text("{}")
    client.containers.get.return_value.put_archive.return_value = False

    with pytest.raises(CoinjoinEmulatorError, match="Failed to copy"):
        driver.upload("client", str(source), "/app/scenario.json")


@pytest.mark.parametrize("status_code", [204, 304])
def test_stop_accepts_running_and_already_stopped_containers(driver_and_client, status_code) -> None:
    driver, client = driver_and_client
    api = Mock()
    response = requests.Response()
    response.status_code = status_code
    response._content = b""
    api.post.return_value = response
    client.containers.get.return_value = Container(
        attrs={"Id": "abc", "Name": "/btc-node"}, client=api, collection=ContainersManager(client=api)
    )

    driver.stop("btc-node")

    api.post.assert_called_once_with(
        "/containers/abc/stop", params={"all": None, "timeout": None}
    )
    api.delete.assert_called_once_with(
        "/containers/abc", params={"force": True, "v": None}
    )


def test_cleanup_uses_the_podman_ownership_filter(driver_and_client) -> None:
    driver, client = driver_and_client
    api = Mock()
    api.get.return_value.json.return_value = [
        {"Id": "btc", "Names": ["btc-node"], "Image": "localhost/btc-node:latest", "State": "running"},
        {"Id": "jm", "Names": ["joinmarket-client"], "Image": "registry/joinmarket-client-server:latest", "State": "exited"},
        {"Id": "wc", "Names": ["wasabi-coordinator"], "Image": "wasabi-coordinator:latest", "State": "exited"},
    ]
    client.containers = ContainersManager(client=api)
    selected = []
    driver.stop_many = lambda names: selected.extend(names)

    driver.cleanup()

    assert selected == ["btc-node", "joinmarket-client", "wasabi-coordinator"]
    assert api.get.call_args.kwargs["params"]["all"] is True
    assert all(
        label in api.get.call_args.kwargs["params"]["filters"]
        for label in managed_label_filters("coinjoin")
    )
    client.networks.get.assert_called_once_with("coinjoin")
    client.networks.get.return_value.remove.assert_called_once_with()


@pytest.mark.parametrize("container_port", [28183, "28183", "28183/tcp"])
def test_run_publishes_the_requested_ports_on_its_own_network(driver_and_client, container_port) -> None:
    driver, client = driver_and_client
    container = Mock()
    container.inspect.return_value = {
        "NetworkSettings": {"Networks": {"coinjoin": {"IPAddress": "10.88.0.7"}}}
    }
    payloads = []

    def run_container(image, **kwargs):
        payloads.append(ContainersManager._render_payload({"image": image, **kwargs}))
        return container

    client.containers.get.side_effect = podman.errors.NotFound("client")
    client.containers.run.side_effect = run_container
    client.networks.get.side_effect = podman.errors.NotFound("coinjoin")
    endpoint = driver.run(
        "client",
        "client:latest",
        env={"MODE": "walletd"},
        ports={container_port: 28184},
        volumes={"/host/data": {"bind": "/container/data", "mode": "rw"}},
        command=["--flag"],
    )

    assert endpoint == ("10.88.0.7", {container_port: 28184}, None)
    client.networks.create.assert_called_once_with("coinjoin")
    assert payloads[0]["portmappings"] == [
        {"container_port": 28183, "host_port": 28184, "protocol": "tcp"}
    ]
    client.containers.run.assert_called_once_with(
        "client:latest",
        command=["--flag"],
        detach=True,
        name="client",
        hostname="client",
        network="coinjoin",
        ports={str(container_port): 28184},
        environment={"MODE": "walletd"},
        volumes={"/host/data": {"bind": "/container/data", "mode": "rw"}},
        labels=managed_labels("coinjoin"),
        sysctls={"net.ipv4.ip_local_reserved_ports": "37127-37260"},
    )


@pytest.mark.parametrize("exists", [False, True])
def test_run_removes_an_existing_container_before_reusing_its_name(driver_and_client, exists) -> None:
    driver, client = driver_and_client
    old_container = Mock()
    if exists:
        client.containers.get.return_value = old_container
        old_container.inspect.return_value = {"Config": {"Labels": managed_labels("coinjoin")}}
    else:
        client.containers.get.side_effect = podman.errors.NotFound("client")
    client.containers.run.return_value.inspect.return_value = {
        "NetworkSettings": {"Networks": {"coinjoin": {"IPAddress": "10.88.0.7"}}}
    }

    def check_removal(image, **kwargs):
        if exists:
            old_container.remove.assert_called_once_with(force=True)
        assert not kwargs.get("auto_remove", False)
        return client.containers.run.return_value

    client.containers.run.side_effect = check_removal
    driver.run("client", "client:latest")
    client.containers.get.assert_called_once_with("client")


@pytest.mark.parametrize(
    "existing_labels",
    [
        managed_labels("another-experiment", "run-42"),
        managed_labels("coinjoin", "another-run"),
    ],
)
def test_run_refuses_to_replace_a_container_from_another_owner(
    driver_and_client, existing_labels
) -> None:
    driver, client = driver_and_client
    driver._run_id = "run-42"  # pylint: disable=protected-access
    existing = client.containers.get.return_value
    existing.inspect.return_value = {"Config": {"Labels": existing_labels}}

    with pytest.raises(CoinjoinEmulatorError, match="Refusing to replace container client"):
        driver.run("client", "client:latest")

    existing.remove.assert_not_called()
    client.containers.run.assert_not_called()


def test_failed_artifact_download_raises_an_emulator_error(driver_and_client) -> None:
    driver, client = driver_and_client
    container = Mock()
    container.get_archive.side_effect = podman.errors.PodmanError("archive unavailable")
    client.containers.get.return_value = container

    with pytest.raises(CoinjoinEmulatorError, match="archive unavailable"):
        driver.download("btc-node", "/missing", "/tmp/logs")
