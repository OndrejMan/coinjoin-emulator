"""Podman driver contracts: the CLI is driven directly, without a Docker daemon."""

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from manager.driver.podman import PodmanDriver
from manager.exceptions import CoinjoinEmulatorError


def test_image_queries_use_podman_only() -> None:
    responses = iter([SimpleNamespace(returncode=0), SimpleNamespace(returncode=1)])

    with patch("manager.driver.podman.subprocess.run", side_effect=lambda *a, **k: next(responses)) as run:
        driver = PodmanDriver()
        assert driver.has_image("present") is True
        assert driver.has_image("missing") is False

    assert run.call_args_list[0].args[0] == ["podman", "image", "exists", "present"]


def test_run_publishes_the_requested_ports_on_its_own_network() -> None:
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout=""),  # stale container removal
            SimpleNamespace(returncode=0, stdout=""),  # network exists
            SimpleNamespace(returncode=0, stdout=""),  # container run
            SimpleNamespace(returncode=0, stdout="10.88.0.7\n"),  # inspect
        ]
    )

    with patch("manager.driver.podman.subprocess.run", side_effect=lambda *a, **k: next(responses)) as run:
        endpoint = PodmanDriver(namespace="coinjoin-test").run(
            "client",
            "client:latest",
            env={"MODE": "walletd"},
            ports={28183: 28184},
            volumes={"/host/data": {"bind": "/container/data", "mode": "rw"}},
            command=["--flag"],
        )

    assert endpoint == ("10.88.0.7", {28183: 28184}, None)
    run_command = next(c.args[0] for c in run.call_args_list if c.args[0][:2] == ["podman", "run"])
    assert run_command[run_command.index("-p") + 1] == "28184:28183"
    assert "/host/data:/container/data:rw" in run_command
    assert run_command[-2:] == ["client:latest", "--flag"]


def test_artifacts_are_copied_with_podman_cp() -> None:
    with patch("manager.driver.podman.subprocess.run") as run:
        driver = PodmanDriver()
        driver.download("btc-node", "/home/bitcoin/data/", "/tmp/btc-data")
        driver.upload("client", "/tmp/scenario.json", "/app/scenario.json")

    assert run.call_args_list[0].args[0] == ["podman", "cp", "btc-node:/home/bitcoin/data/", "/tmp/btc-data"]
    assert run.call_args_list[1].args[0] == ["podman", "cp", "/tmp/scenario.json", "client:/app/scenario.json"]


def test_a_failed_copy_reports_what_podman_said() -> None:
    failure = subprocess.CalledProcessError(
        returncode=125, cmd=["podman", "cp"], stderr="Error: no such file or directory\n"
    )

    with patch("manager.driver.podman.subprocess.run", side_effect=failure):
        with pytest.raises(CoinjoinEmulatorError, match="no such file or directory"):
            PodmanDriver().download("btc-node", "/missing", "/tmp/logs")


def test_cleanup_includes_exited_containers_and_removes_the_network() -> None:
    listing = SimpleNamespace(
        returncode=0,
        stdout=(
            "btc-node\tbtc-node:latest\n"
            "unrelated\tpostgres:latest\n"
            "joinmarket-client\tregistry/joinmarket-client-server:latest\n"
        ),
    )

    with (
        patch("manager.driver.podman.subprocess.run", return_value=listing) as run,
        patch.object(PodmanDriver, "stop_many") as stop_many,
    ):
        PodmanDriver(namespace="coinjoin-test").cleanup()

    assert run.call_args_list[0].args[0] == ["podman", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}"]
    stop_many.assert_called_once_with(["btc-node", "joinmarket-client"])
    assert run.call_args_list[-1].args[0] == ["podman", "network", "rm", "coinjoin-test"]
