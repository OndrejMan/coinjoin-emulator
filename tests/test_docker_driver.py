"""Docker artifact-transfer failure semantics."""

from typing import cast
from unittest.mock import Mock

import docker
import pytest

from manager.driver.docker import DockerDriver


def test_download_surfaces_missing_container() -> None:
    driver = object.__new__(DockerDriver)
    client = Mock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    driver.client = cast(docker.DockerClient, client)

    with pytest.raises(RuntimeError, match="Failed to download btc-node"):
        driver.download("btc-node", "/home/bitcoin/data", "/tmp/output")
