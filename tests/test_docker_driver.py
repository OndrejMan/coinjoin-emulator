"""Docker driver contracts for endpoint resolution and artifact collection."""

from types import SimpleNamespace
from unittest.mock import Mock

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
