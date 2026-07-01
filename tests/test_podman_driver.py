import subprocess
from unittest.mock import patch

import pytest

from manager.driver.podman import PodmanDriver
from manager.exceptions import CoinjoinEmulatorError


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
