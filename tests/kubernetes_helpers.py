"""Shared fakes for the Kubernetes driver tests.

The suite runs without the ``kubernetes`` package installed, so the driver's
imports are satisfied by the stand-in modules installed here.
"""

import importlib
import importlib.util
import sys
import types
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

# pylint: disable=protected-access

if TYPE_CHECKING:
    from manager.driver.kubernetes import KubernetesDriver as KubernetesDriverClass
    from manager.driver.kubernetes_port_forward import PortForwardServer as PortForwardServerClass


def _install_fake_kubernetes_modules() -> None:
    if importlib.util.find_spec("kubernetes") is not None:
        return

    kubernetes_module = types.ModuleType("kubernetes")
    client_module = types.ModuleType("kubernetes.client")
    config_module = types.ModuleType("kubernetes.config")
    stream_module = types.ModuleType("kubernetes.stream")
    exceptions_module = types.ModuleType("kubernetes.client.exceptions")
    config_exception_module = types.ModuleType("kubernetes.config.config_exception")
    models_module = types.ModuleType("kubernetes.client.models")
    core_v1_event_module = types.ModuleType("kubernetes.client.models.core_v1_event")
    v1_pod_module = types.ModuleType("kubernetes.client.models.v1_pod")

    class ApiException(Exception):
        pass

    class _FakeConfigException(Exception):
        pass

    setattr(client_module, "CoreV1Api", object)
    setattr(client_module, "V1DeleteOptions", object)
    setattr(core_v1_event_module, "CoreV1Event", object)
    setattr(v1_pod_module, "V1Pod", object)
    setattr(config_module, "load_kube_config", lambda: None)
    setattr(config_module, "load_incluster_config", lambda: None)
    setattr(stream_module, "portforward", lambda *args, **kwargs: None)
    setattr(stream_module, "stream", lambda *args, **kwargs: None)
    setattr(exceptions_module, "ApiException", ApiException)
    setattr(config_exception_module, "ConfigException", _FakeConfigException)

    setattr(kubernetes_module, "client", client_module)
    setattr(kubernetes_module, "config", config_module)

    sys.modules["kubernetes"] = kubernetes_module
    sys.modules["kubernetes.client"] = client_module
    sys.modules["kubernetes.config"] = config_module
    sys.modules["kubernetes.stream"] = stream_module
    sys.modules["kubernetes.client.exceptions"] = exceptions_module
    sys.modules["kubernetes.config.config_exception"] = config_exception_module
    sys.modules["kubernetes.client.models"] = models_module
    sys.modules["kubernetes.client.models.core_v1_event"] = core_v1_event_module
    sys.modules["kubernetes.client.models.v1_pod"] = v1_pod_module


def load_kubernetes_symbols() -> tuple[type["KubernetesDriverClass"], type["PortForwardServerClass"]]:
    _install_fake_kubernetes_modules()
    module = importlib.import_module("manager.driver.kubernetes")
    return (
        cast(type["KubernetesDriverClass"], module.KubernetesDriver),
        cast(type["PortForwardServerClass"], module.PortForwardServer),
    )


class FakePortForwardServer:
    next_port = 41000
    started: list["FakePortForwardServer"] = []

    def __init__(
        self,
        kube_client: object,
        namespace: str,
        pod_name: str,
        remote_port: int,
    ) -> None:
        self.kube_client = kube_client
        self.namespace = namespace
        self.pod_name = pod_name
        self.remote_port = remote_port
        self.local_port = FakePortForwardServer.next_port
        FakePortForwardServer.next_port += 1

    @classmethod
    def reset(cls) -> None:
        cls.next_port = 41000
        cls.started = []

    def start(self) -> None:
        FakePortForwardServer.started.append(self)

    def close(self) -> None:
        pass


def capture_service_body(
    service_bodies: list[dict[str, object]],
    body: dict[str, object],
) -> SimpleNamespace:
    service_bodies.append(body)
    return SimpleNamespace(
        spec=SimpleNamespace(
            ports=[
                SimpleNamespace(target_port=18443, node_port=31843),
            ]
        )
    )


def run_driver_with_mapped_volume(
    *, run_id: str | None = None
) -> tuple[
    "KubernetesDriverClass", str, dict[int, int], list[dict[str, object]], list[dict[str, object]]
]:
    KubernetesDriver, _ = load_kubernetes_symbols()
    FakePortForwardServer.reset()
    pod_bodies: list[dict[str, object]] = []
    service_bodies: list[dict[str, object]] = []
    kube_client = SimpleNamespace(
        create_namespaced_pod=lambda **kwargs: pod_bodies.append(cast(dict[str, object], kwargs["body"])),
        read_namespaced_pod_status=lambda **kwargs: SimpleNamespace(status=SimpleNamespace(pod_ip="10.42.0.10")),
        create_namespaced_service=lambda **kwargs: capture_service_body(
            service_bodies,
            cast(dict[str, object], kwargs["body"]),
        ),
    )

    with (
        patch("manager.driver.kubernetes.config.load_kube_config"),
        patch(
            "manager.driver.kubernetes.client.CoreV1Api",
            return_value=kube_client,
        ),
        patch(
            "manager.driver.kubernetes.PortForwardServer",
            FakePortForwardServer,
        ),
    ):
        driver = KubernetesDriver(
            namespace="coinjoin-test",
            reuse_namespace=True,
            run_id=run_id,
        )
        pod_ip, ports = driver.run(
            "btc-node",
            "btc-node:latest",
            ports={18443: 18443},
            cpu=0.5,
            cpu_request=0.1,
            command=["./run.sh", "-blocksxor=0"],
            volumes={
                "/tmp/btc-data": {
                    "bind": "/home/bitcoin/data",
                    "mode": "rw",
                    "uid": "1234",
                    "gid": "5678",
                }
            },
        )

    return driver, pod_ip, ports, pod_bodies, service_bodies
