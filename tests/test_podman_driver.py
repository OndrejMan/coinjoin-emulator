import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from manager.driver.podman import PodmanDriver
from manager.exceptions import CoinjoinEmulatorError


def test_run_removes_stale_container_and_keeps_crash_logs() -> None:
    with patch("manager.driver.podman.subprocess.run") as run:
        run.return_value.returncode = 0
        PodmanDriver(namespace="coinjoin-test").run("wasabi-coordinator", "wasabi-coordinator:2.6.0")

    commands = [call.args[0] for call in run.call_args_list]
    remove_command = ["podman", "rm", "--force", "--ignore", "wasabi-coordinator"]
    assert remove_command in commands
    run_command = next(command for command in commands if command[:2] == ["podman", "run"])
    # No --rm: a crashed container must keep its logs readable for retries.
    assert "--rm" not in run_command
    assert commands.index(remove_command) < commands.index(run_command)


def test_run_keeps_wasabi_ports_out_of_the_containers_ephemeral_pool() -> None:
    with patch("manager.driver.podman.subprocess.run") as run:
        run.return_value.returncode = 0
        PodmanDriver(namespace="coinjoin-test").run("wasabi-coordinator", "wasabi-coordinator:2.6.0")

    commands = [call.args[0] for call in run.call_args_list]
    run_command = next(command for command in commands if command[:2] == ["podman", "run"])
    sysctl_index = run_command.index("--sysctl")
    assert run_command[sysctl_index + 1] == "net.ipv4.ip_local_reserved_ports=37127-37260"


def test_stop_removes_container_after_stopping() -> None:
    with patch("manager.driver.podman.subprocess.run") as run:
        run.return_value.returncode = 0
        PodmanDriver().stop("wasabi-coordinator")

    commands = [call.args[0] for call in run.call_args_list]
    assert ["podman", "stop", "wasabi-coordinator"] in commands
    assert ["podman", "rm", "--force", "--ignore", "wasabi-coordinator"] in commands


def test_stop_removes_exited_container_without_stopping_it() -> None:
    responses = iter(
        [
            SimpleNamespace(returncode=1),  # container exists -> no
            SimpleNamespace(returncode=0),  # rm --force --ignore
        ]
    )

    with patch("manager.driver.podman.subprocess.run", side_effect=lambda *a, **k: next(responses)) as run:
        PodmanDriver().stop("wasabi-coordinator")

    commands = [call.args[0] for call in run.call_args_list]
    assert ["podman", "stop", "wasabi-coordinator"] not in commands
    assert ["podman", "rm", "--force", "--ignore", "wasabi-coordinator"] in commands


def test_cleanup_lists_exited_containers_too() -> None:
    with patch("manager.driver.podman.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        PodmanDriver().cleanup()

    assert run.call_args_list[0].args[0][:3] == ["podman", "ps", "-a"]


def test_download_copies_container_path_with_podman_cp() -> None:
    with patch("manager.driver.podman.subprocess.run") as run:
        PodmanDriver().download("btc-node", "/home/bitcoin/data/", "/tmp/btc-data")

    run.assert_called_once_with(
        ["podman", "cp", "btc-node:/home/bitcoin/data/", "/tmp/btc-data"],
        check=True,
        stdout=None,
        stderr=None,
        capture_output=True,
        text=True,
    )


def test_download_reports_podman_cp_failure() -> None:
    failure = subprocess.CalledProcessError(
        returncode=125,
        cmd=["podman", "cp", "btc-node:/missing", "/tmp/logs"],
        stderr="Error: no such file or directory\n",
    )

    with patch("manager.driver.podman.subprocess.run", side_effect=failure):
        with pytest.raises(CoinjoinEmulatorError) as error:
            PodmanDriver().download("btc-node", "/missing", "/tmp/logs")

    assert "Failed to copy btc-node:/missing to /tmp/logs" in str(error.value)
    assert "no such file or directory" in str(error.value)
