"""Podman driver contracts against the pinned Python SDK."""

import tarfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import podman
import pytest
import requests
from podman.api.client import APIClient
from podman.domain.containers import Container
from podman.domain.containers_manager import ContainersManager

from manager.driver import managed_label_filters, managed_labels
from manager.driver.podman import PodmanDriver
from manager.exceptions import CoinjoinEmulatorError


@pytest.fixture
def driver_and_client():
    with patch("manager.driver.podman.podman.PodmanClient") as client_class:
        yield PodmanDriver(run_id="run-42"), client_class.return_value


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


def test_direct_runs_get_distinct_cleanup_labels() -> None:
    with patch("manager.driver.podman.podman.PodmanClient"):
        first = PodmanDriver()
        second = PodmanDriver()

    assert first._run_id.startswith("local-")  # pylint: disable=protected-access
    assert first._run_id != second._run_id  # pylint: disable=protected-access


def test_artifact_transfer_uses_the_podman_archive_api(driver_and_client, tmp_path) -> None:
    driver, client = driver_and_client
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        content = b"backend log"
        entry = tarfile.TarInfo("backend.log")
        entry.size = len(content)
        tar.addfile(entry, BytesIO(content))

    container = Mock()
    container.id = "btc-id"
    response = client.api.get.return_value
    response.iter_content.return_value = iter([archive.getvalue()])
    container.put_archive.return_value = True
    client.containers.get.return_value = container
    source = tmp_path / "scenario.json"
    source.write_text("{}")
    destination = tmp_path / "download"
    destination.mkdir()
    driver.download("btc-node", "/var/log/backend", str(destination))
    driver.upload("client", str(source), "/app/scenario.json")

    assert (destination / "backend.log").read_text() == "backend log"
    client.api.get.assert_called_once_with(
        "/containers/btc-id/archive", params={"path": ["/var/log/backend"]}, stream=True
    )
    response.close.assert_called_once_with()
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


def test_logs_include_stdout_and_stderr(driver_and_client) -> None:
    driver, client = driver_and_client
    container = client.containers.get.return_value
    container.logs.return_value = b"startup output\nerror: \xff\n"

    assert driver.logs("wasabi-coordinator") == "startup output\nerror: \ufffd\n"

    client.containers.get.assert_called_once_with("wasabi-coordinator")
    container.logs.assert_called_once_with(stdout=True, stderr=True)


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


def test_explicit_clean_uses_the_podman_namespace_filter(driver_and_client) -> None:
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

    driver.cleanup_all()

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
        labels=managed_labels("coinjoin", "run-42"),
        sysctls={"net.ipv4.ip_local_reserved_ports": "37127-37260"},
    )


@pytest.mark.parametrize("exists", [False, True])
def test_run_preserves_an_existing_stopped_container_before_reusing_its_name(driver_and_client, exists) -> None:
    driver, client = driver_and_client
    old_container = Mock()
    if exists:
        client.containers.get.return_value = old_container
        old_container.inspect.return_value = {
            "Id": "old-container-id",
            "Config": {"Labels": managed_labels("coinjoin", "old-run")},
            "State": {"Status": "exited"},
        }
    else:
        client.containers.get.side_effect = podman.errors.NotFound("client")
    client.containers.run.return_value.inspect.return_value = {
        "NetworkSettings": {"Networks": {"coinjoin": {"IPAddress": "10.88.0.7"}}}
    }

    def check_preservation(image, **kwargs):
        if exists:
            old_container.rename.assert_called_once_with("coinjoin-stale-old-container-id")
            old_container.remove.assert_not_called()
        assert not kwargs.get("auto_remove", False)
        return client.containers.run.return_value

    client.containers.run.side_effect = check_preservation
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


def test_run_refuses_to_replace_a_running_container_from_another_run(driver_and_client) -> None:
    driver, client = driver_and_client
    existing = client.containers.get.return_value
    existing.inspect.return_value = {
        "Id": "old-container-id",
        "Config": {"Labels": managed_labels("coinjoin", "old-run")},
        "State": {"Status": "running"},
    }

    with pytest.raises(CoinjoinEmulatorError, match="state is running"):
        driver.run("client", "client:latest")

    existing.rename.assert_not_called()
    client.containers.run.assert_not_called()


def test_normal_cleanup_uses_the_current_run_id_and_keeps_an_existing_network(driver_and_client) -> None:
    driver, client = driver_and_client
    client.containers.list.return_value = [
        SimpleNamespace(name="coinjoin-stale-old-container-id"),
        SimpleNamespace(name="btc-node"),
    ]
    selected = []
    driver.stop_many = lambda names: selected.extend(names)

    driver.cleanup()

    assert selected == ["btc-node"]
    assert client.containers.list.call_args.kwargs["filters"] == {
        "label": managed_label_filters("coinjoin", "run-42")
    }
    client.networks.get.assert_not_called()


def test_pause_and_unpause_freeze_the_container(driver_and_client) -> None:
    driver, client = driver_and_client
    container = client.containers.get.return_value

    driver.pause("btc-node")
    driver.unpause("btc-node")

    container.pause.assert_called_once_with()
    container.unpause.assert_called_once_with()


def test_a_failed_pause_raises_an_emulator_error(driver_and_client) -> None:
    driver, client = driver_and_client
    client.containers.get.return_value.pause.side_effect = podman.errors.PodmanError("no freezer")

    with pytest.raises(CoinjoinEmulatorError, match="Failed to pause btc-node"):
        driver.pause("btc-node")


def test_failed_artifact_download_raises_an_emulator_error(driver_and_client) -> None:
    driver, client = driver_and_client
    container = Mock()
    client.api.get.return_value.raise_for_status.side_effect = podman.errors.PodmanError("archive unavailable")
    client.containers.get.return_value = container

    with pytest.raises(CoinjoinEmulatorError, match="archive unavailable"):
        driver.download("btc-node", "/missing", "/tmp/logs")

    client.api.get.return_value.close.assert_called_once_with()


@pytest.mark.parametrize("broken", [False, True])
def test_download_streams_through_the_real_sdk_and_closes_http(tmp_path, broken) -> None:
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        entry = tarfile.TarInfo("data/block.dat")
        entry.size = 5
        tar.addfile(entry, BytesIO(b"block"))
    closed = []

    class Body(BytesIO):
        def read(self, size=-1):
            if broken and self.tell():
                raise OSError("broken transfer")
            return super().read(size)

    class Response(requests.Response):
        def close(self):
            closed.append(True)
            super().close()

    class Adapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            assert kwargs["stream"] is True
            assert request.path_url.endswith("/containers/btc-id/archive?path=%2Fdata")
            response = Response()
            response.status_code = 200
            response.raw = Body(archive.getvalue())
            return response

        def close(self):
            pass

    with APIClient(base_url="http://localhost:12345", version="4.7.0") as api:
        api.mount("http://", Adapter())
        instance = object.__new__(PodmanDriver)
        instance.client = SimpleNamespace(api=api, containers=Mock())
        instance.client.containers.get.return_value = Container(attrs={"Id": "btc-id"}, client=api)
        if broken:
            with pytest.raises(CoinjoinEmulatorError, match="broken transfer"):
                instance.download("btc-node", "/data", str(tmp_path))
            assert list(tmp_path.iterdir()) == []
        else:
            instance.download("btc-node", "/data", str(tmp_path))
            assert (tmp_path / "data/block.dat").read_bytes() == b"block"
    assert closed == [True]
