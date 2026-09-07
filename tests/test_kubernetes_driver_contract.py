"""Kubernetes driver contracts that keep a shared namespace usable."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from manager.driver.kubernetes import MANAGED_BY_LABEL, MANAGED_BY_VALUE, KubernetesDriver
from manager.exceptions import KubernetesResourceQuotaError, StartupError


def driver(**overrides: object) -> KubernetesDriver:
    instance = object.__new__(KubernetesDriver)
    instance.client = Mock()
    instance._namespace = "coinjoin"  # pylint: disable=protected-access
    instance.reuse_namespace = True
    instance.pull_secret_path = None
    instance.in_cluster = False
    instance.run_id = None
    for key, value in overrides.items():
        setattr(instance, key, value)
    return instance


def test_pods_and_services_are_labelled_with_the_run() -> None:
    manifest = driver(run_id="run-42").build_pod_manifest(
        "btc-node", "btc-node:latest", {}, {18443: 18443}, 1.0, 512
    )

    assert manifest["metadata"]["labels"] == {
        "app": "btc-node",
        MANAGED_BY_LABEL: MANAGED_BY_VALUE,
        "coinjoin.run-id": "run-42",
    }


def test_a_host_path_is_mounted_and_a_command_overrides_the_entrypoint() -> None:
    manifest = driver().build_pod_manifest(
        "btc-node",
        "btc-node:latest",
        {},
        {18443: 18443},
        1.0,
        512,
        volumes={"/data/btc": {"bind": "/home/bitcoin/data", "mode": "rw"}},
        command=["./run.sh", "-prune=0"],
    )

    container = manifest["spec"]["containers"][0]
    assert manifest["spec"]["volumes"] == [
        {"name": "host-volume-0", "hostPath": {"path": "/data/btc", "type": "DirectoryOrCreate"}}
    ]
    assert container["volumeMounts"] == [
        {"name": "host-volume-0", "mountPath": "/home/bitcoin/data", "readOnly": False}
    ]
    assert container["command"] == ["./run.sh", "-prune=0"]


def test_cleanup_only_touches_resources_this_emulator_created() -> None:
    instance = driver()
    instance.client.list_namespaced_pod.return_value = SimpleNamespace(
        items=[SimpleNamespace(metadata=SimpleNamespace(name="btc-node"))]
    )
    instance.client.list_namespaced_service.return_value = SimpleNamespace(items=[])

    instance.cleanup()

    selector = f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}"
    assert instance.client.list_namespaced_pod.call_args.kwargs["label_selector"] == selector
    assert instance.client.list_namespaced_service.call_args.kwargs["label_selector"] == selector
    instance.client.delete_namespaced_pod.assert_called_once_with(
        name="btc-node", namespace="coinjoin"
    )


def test_a_quota_rejection_is_reported_as_a_quota_error() -> None:
    instance = driver()
    rejection = ApiException(status=403)
    rejection.body = 'pods "btc-node" is forbidden: exceeded quota: cpu'
    instance.client.create_namespaced_pod.side_effect = rejection

    with pytest.raises(KubernetesResourceQuotaError):
        instance.run("btc-node", "btc-node:latest", ports={18443: 18443}, cpu=1.0, memory=512)


def test_a_pod_that_terminates_before_it_gets_an_ip_fails_the_run() -> None:
    instance = driver()
    instance.client.read_namespaced_pod_status.return_value = SimpleNamespace(
        status=SimpleNamespace(pod_ip=None, phase="Failed", reason="Evicted", message="no memory")
    )

    with pytest.raises(StartupError, match="terminal phase Failed"):
        instance._wait_for_pod_ip("btc-node")  # pylint: disable=protected-access


def test_waiting_for_a_pod_ip_has_a_deadline() -> None:
    instance = driver()
    instance.client.read_namespaced_pod_status.return_value = SimpleNamespace(
        status=SimpleNamespace(pod_ip=None, phase="Pending", reason=None, message=None)
    )

    with patch("manager.driver.kubernetes.time.monotonic", side_effect=[0.0, 10_000.0]):
        with pytest.raises(TimeoutError, match="did not receive an IP"):
            instance._wait_for_pod_ip("btc-node")  # pylint: disable=protected-access
