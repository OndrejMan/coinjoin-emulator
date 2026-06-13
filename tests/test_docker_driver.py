import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import docker  # noqa: F401
except ModuleNotFoundError:
    docker_module = types.ModuleType("docker")
    docker_models_module = types.ModuleType("docker.models")
    docker_containers_module = types.ModuleType("docker.models.containers")

    class ImageNotFound(Exception):
        pass

    class NotFound(Exception):
        pass

    class APIError(Exception):
        def __init__(self, message="", response=None, explanation=None):
            super().__init__(message)
            self.response = response
            self.explanation = explanation

    docker_module.from_env = lambda: None
    docker_module.errors = SimpleNamespace(
        ImageNotFound=ImageNotFound,
        NotFound=NotFound,
        APIError=APIError,
    )
    docker_containers_module.Container = object

    sys.modules["docker"] = docker_module
    sys.modules["docker.models"] = docker_models_module
    sys.modules["docker.models.containers"] = docker_containers_module

import docker

from manager.driver.docker import DockerDriver


class DockerDriverTest(unittest.TestCase):
    def test_run_keeps_container_until_cleanup_for_log_inspection(self):
        client = Mock()
        client.networks.create.return_value = SimpleNamespace(id="coinjoin-network-id")
        client.containers.run.return_value = None
        client.containers.get.side_effect = docker.errors.NotFound()

        with patch("manager.driver.docker.docker.from_env", return_value=client):
            driver = DockerDriver(namespace="coinjoin-test")
            driver.run("joinmarket-distributor", "joinmarket-client-server:latest")

        self.assertFalse(client.containers.run.call_args.kwargs["auto_remove"])

    def test_run_removes_stale_container_before_reusing_name(self):
        stale_container = Mock()
        client = Mock()
        client.networks.create.return_value = SimpleNamespace(id="coinjoin-network-id")
        client.containers.get.return_value = stale_container
        client.containers.run.return_value = None

        with patch("manager.driver.docker.docker.from_env", return_value=client):
            driver = DockerDriver(namespace="coinjoin-test")
            driver.run("btc-node", "btc-node:latest")

        client.containers.get.assert_called_once_with("btc-node")
        stale_container.remove.assert_called_once_with(force=True)
        client.containers.run.assert_called_once()

    def test_run_retries_after_docker_name_conflict(self):
        stale_container = Mock()
        conflict = docker.errors.APIError(
            "conflict",
            explanation='Conflict. The container name "/btc-node" is already in use.',
        )
        client = Mock()
        client.networks.create.return_value = SimpleNamespace(id="coinjoin-network-id")
        client.containers.get.side_effect = [docker.errors.NotFound(), stale_container]
        client.containers.run.side_effect = [conflict, None]

        with patch("manager.driver.docker.docker.from_env", return_value=client):
            driver = DockerDriver(namespace="coinjoin-test")
            driver.run("btc-node", "btc-node:latest")

        self.assertEqual(client.containers.get.call_count, 2)
        stale_container.remove.assert_called_once_with(force=True)
        self.assertEqual(client.containers.run.call_count, 2)

    def test_cleanup_includes_exited_emulator_containers(self):
        matching_container = Mock()
        matching_container.name = "joinmarket-distributor"
        matching_container.attrs = {
            "Config": {"Image": "ghcr.io/ondrejman/joinmarket-client-server:latest"}
        }
        other_container = Mock()
        other_container.name = "unrelated"
        other_container.attrs = {"Config": {"Image": "alpine:latest"}}

        client = Mock()
        client.containers.list.return_value = [matching_container, other_container]
        client.containers.get.return_value = matching_container
        client.networks.list.return_value = []

        with patch("manager.driver.docker.docker.from_env", return_value=client):
            driver = DockerDriver(namespace="coinjoin-test")
            driver.cleanup()

        client.containers.list.assert_called_once_with(all=True)
        client.containers.get.assert_called_once_with("joinmarket-distributor")
        matching_container.stop.assert_called_once_with()
        matching_container.remove.assert_called_once_with(force=True)
        other_container.stop.assert_not_called()
        other_container.remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
