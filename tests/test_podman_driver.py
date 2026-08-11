import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from manager.driver.podman import PodmanDriver
from manager.exceptions import CoinjoinEmulatorError


def test_image_operations_use_podman() -> None:
    responses = iter(
        [
            SimpleNamespace(returncode=0),
            SimpleNamespace(returncode=1),
        ]
    )
    with patch("manager.driver.podman.subprocess.run", side_effect=lambda *args, **kwargs: next(responses)) as run:
        driver = PodmanDriver()
        assert driver.has_image("present") is True
        assert driver.has_image("missing") is False

    assert run.call_args_list[0].args[0] == ["podman", "image", "exists", "present"]
    assert run.call_args_list[1].args[0] == ["podman", "image", "exists", "missing"]

    with patch("manager.driver.podman.subprocess.run") as run:
        driver.build("image", "containers/image")
        driver.pull("registry/image")

    assert run.call_args_list[0].args[0] == [
        "podman", "build", "--rm", "--no-cache", "-t", "image", "containers/image"
    ]
    assert run.call_args_list[1].args[0] == ["podman", "pull", "registry/image"]


def test_run_uses_podman_network_and_preserves_three_part_endpoint() -> None:
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout=""),  # stale-container removal
            SimpleNamespace(returncode=0, stdout=""),  # network exists
            SimpleNamespace(returncode=0, stdout=""),  # container run
            SimpleNamespace(returncode=0, stdout="10.88.0.7\n"),  # inspect IP
        ]
    )
    with patch("manager.driver.podman.subprocess.run", side_effect=lambda *args, **kwargs: next(responses)) as run:
        endpoint = PodmanDriver(namespace="coinjoin-test").run(
            "client",
            "client:latest",
            env={"MODE": "walletd"},
            ports={28183: 28184},
            volumes={"/host/data": {"bind": "/container/data", "mode": "rw"}},
            command=["--flag"],
        )

    assert endpoint == ("10.88.0.7", {28183: 28184}, None)
    commands = [call.args[0] for call in run.call_args_list]
    run_command = next(command for command in commands if command[:2] == ["podman", "run"])
    assert "--rm" not in run_command
    assert ["-p", "28184:28183"] == run_command[run_command.index("-p") : run_command.index("-p") + 2]
    assert "/host/data:/container/data:rw" in run_command
    assert run_command[-2:] == ["client:latest", "--flag"]


def test_download_and_upload_use_podman_cp() -> None:
    with patch("manager.driver.podman.subprocess.run") as run:
        driver = PodmanDriver()
        driver.download("btc-node", "/home/bitcoin/data/", "/tmp/btc-data")
        driver.upload("client", "/tmp/scenario.json", "/app/scenario.json")

    assert run.call_args_list[0].args[0] == [
        "podman", "cp", "btc-node:/home/bitcoin/data/", "/tmp/btc-data"
    ]
    assert run.call_args_list[1].args[0] == [
        "podman", "cp", "/tmp/scenario.json", "client:/app/scenario.json"
    ]


def test_download_reports_podman_cp_failure() -> None:
    failure = subprocess.CalledProcessError(
        returncode=125,
        cmd=["podman", "cp", "btc-node:/missing", "/tmp/logs"],
        stderr="Error: no such file or directory\n",
    )

    with patch("manager.driver.podman.subprocess.run", side_effect=failure):
        with pytest.raises(CoinjoinEmulatorError, match="Failed to copy btc-node:/missing") as error:
            PodmanDriver().download("btc-node", "/missing", "/tmp/logs")

    assert "no such file or directory" in str(error.value)


def test_cleanup_uses_podman_and_includes_exited_containers() -> None:
    listing = SimpleNamespace(
        returncode=0,
        stdout=(
            "btc-node\tbtc-node:latest\n"
            "unrelated\tpostgres:latest\n"
            "joinmarket-client\tregistry/joinmarket-client-server:latest\n"
        ),
        stderr="",
    )
    with (
        patch("manager.driver.podman.subprocess.run", return_value=listing) as run,
        patch.object(PodmanDriver, "stop_many") as stop_many,
    ):
        PodmanDriver(namespace="coinjoin-test").cleanup()

    assert run.call_args_list[0].args[0] == [
        "podman", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}"
    ]
    stop_many.assert_called_once_with(["btc-node", "joinmarket-client"])
    assert run.call_args_list[-1].args[0] == ["podman", "network", "rm", "coinjoin-test"]
