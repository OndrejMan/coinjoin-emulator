import importlib.util
import sys
import types
from types import SimpleNamespace
from typing import cast
from unittest import TestCase
from unittest.mock import patch

from manager.driver.kubernetes import KubernetesDriver

if importlib.util.find_spec("kubernetes") is None:
    kubernetes_module = types.ModuleType("kubernetes")
    client_module = types.ModuleType("kubernetes.client")
    config_module = types.ModuleType("kubernetes.config")
    stream_module = types.ModuleType("kubernetes.stream")
    exceptions_module = types.ModuleType("kubernetes.client.exceptions")

    class ApiException(Exception):
        pass

    setattr(client_module, "CoreV1Api", object)
    setattr(client_module, "V1DeleteOptions", object)
    setattr(config_module, "load_kube_config", lambda: None)
    setattr(stream_module, "portforward", lambda *args, **kwargs: None)
    setattr(stream_module, "stream", lambda *args, **kwargs: None)
    setattr(exceptions_module, "ApiException", ApiException)

    setattr(kubernetes_module, "client", client_module)
    setattr(kubernetes_module, "config", config_module)

    sys.modules["kubernetes"] = kubernetes_module
    sys.modules["kubernetes.client"] = client_module
    sys.modules["kubernetes.config"] = config_module
    sys.modules["kubernetes.stream"] = stream_module
    sys.modules["kubernetes.client.exceptions"] = exceptions_module


class KubernetesDriverTest(TestCase):
    def test_run_accepts_and_maps_docker_style_volumes(self) -> None:
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

            def start(self) -> None:
                FakePortForwardServer.started.append(self)

            def close(self) -> None:
                pass

        kube_client = SimpleNamespace(
            create_namespaced_pod=lambda **kwargs: None,
            read_namespaced_pod_status=lambda **kwargs: SimpleNamespace(
                status=SimpleNamespace(pod_ip="10.42.0.10")
            ),
            create_namespaced_service=lambda **kwargs: SimpleNamespace(
                spec=SimpleNamespace(
                    ports=[
                        SimpleNamespace(target_port=18443, node_port=31843),
                    ]
                )
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
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            pod_bodies: list[dict[str, object]] = []
            service_bodies: list[dict[str, object]] = []

            def create_pod(**kwargs: object) -> None:
                pod_bodies.append(cast(dict[str, object], kwargs["body"]))

            def create_service(**kwargs: object) -> SimpleNamespace:
                service_bodies.append(cast(dict[str, object], kwargs["body"]))
                return SimpleNamespace(
                    spec=SimpleNamespace(
                        ports=[
                            SimpleNamespace(target_port=18443, node_port=31843),
                        ]
                    )
                )

            kube_client.create_namespaced_pod = create_pod
            kube_client.create_namespaced_service = create_service

            pod_ip, ports = driver.run(
                "btc-node",
                "btc-node:latest",
                ports={18443: 18443},
                command=["./run.sh", "-blocksxor=0"],
                volumes={
                    "/tmp/btc-data": {
                        "bind": "/home/bitcoin/data",
                        "mode": "rw",
                    }
                },
            )

        self.assertEqual(pod_ip, "10.42.0.10")
        self.assertEqual(driver.control_host, "127.0.0.1")
        self.assertEqual(ports, {18443: 41000})
        self.assertEqual(len(FakePortForwardServer.started), 1)
        self.assertEqual(FakePortForwardServer.started[0].namespace, "coinjoin-test")
        self.assertEqual(FakePortForwardServer.started[0].pod_name, "btc-node")
        self.assertEqual(FakePortForwardServer.started[0].remote_port, 18443)
        service_spec = cast(dict[str, object], service_bodies[0]["spec"])
        service_ports = cast(list[dict[str, object]], service_spec["ports"])
        self.assertNotIn("nodePort", service_ports[0])
        service_metadata = cast(dict[str, object], service_bodies[0]["metadata"])
        service_labels = cast(dict[str, object], service_metadata["labels"])
        self.assertEqual(service_labels["app.kubernetes.io/managed-by"], "coinjoin-emulator")

        pod_metadata = cast(dict[str, object], pod_bodies[0]["metadata"])
        pod_labels = cast(dict[str, object], pod_metadata["labels"])
        self.assertEqual(pod_labels["app.kubernetes.io/managed-by"], "coinjoin-emulator")
        pod_spec = cast(dict[str, object], pod_bodies[0]["spec"])
        containers = cast(list[dict[str, object]], pod_spec["containers"])
        container = containers[0]
        self.assertEqual(container["command"], ["./run.sh", "-blocksxor=0"])
        self.assertEqual(
            container["volumeMounts"],
            [
                {
                    "name": "host-volume-0",
                    "mountPath": "/home/bitcoin/data",
                    "readOnly": False,
                }
            ],
        )
        self.assertEqual(
            pod_spec["volumes"],
            [
                {
                    "name": "host-volume-0",
                    "hostPath": {
                        "path": "/tmp/btc-data",
                        "type": "DirectoryOrCreate",
                    },
                }
            ],
        )

    def test_run_does_not_create_empty_service_when_no_ports_are_exposed(self) -> None:
        created_pods: list[dict[str, object]] = []

        def create_pod(**kwargs: object) -> None:
            created_pods.append(cast(dict[str, object], kwargs["body"]))

        def create_service(**_kwargs: object) -> None:
            raise AssertionError("service should not be created for a pod with no exposed ports")

        kube_client = SimpleNamespace(
            create_namespaced_pod=create_pod,
            create_namespaced_service=create_service,
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=kube_client,
            ),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            pod_ip, ports = driver.run(
                "joinmarket-client-server-0",
                "joinmarket-client-server:latest",
                ports={},
                skip_ip=True,
            )

        self.assertEqual(pod_ip, "")
        self.assertEqual(ports, {})
        self.assertEqual(created_pods[0]["kind"], "Pod")

    def test_cleanup_uses_fresh_client_and_deletes_managed_resources(self) -> None:
        closed_forwards: list[str] = []
        deleted_pods: list[str] = []
        deleted_services: list[str] = []

        class FakeForward:
            def close(self) -> None:
                closed_forwards.append("closed")

        def corrupted_list_pods(**_kwargs: object) -> None:
            raise ValueError("Missing required parameter `ports`")

        regular_client = SimpleNamespace(list_namespaced_pod=corrupted_list_pods)
        cleanup_client = SimpleNamespace(
            list_namespaced_pod=lambda **_kwargs: SimpleNamespace(
                items=[
                    SimpleNamespace(
                        metadata=SimpleNamespace(
                            name="wallet-helper",
                            labels={"app.kubernetes.io/managed-by": "coinjoin-emulator"},
                        )
                    ),
                    SimpleNamespace(metadata=SimpleNamespace(name="unrelated", labels={})),
                    SimpleNamespace(metadata=SimpleNamespace(name="btc-node-old", labels={})),
                ]
            ),
            list_namespaced_service=lambda **_kwargs: SimpleNamespace(
                items=[
                    SimpleNamespace(
                        metadata=SimpleNamespace(
                            name="wallet-helper-service",
                            labels={"app.kubernetes.io/managed-by": "coinjoin-emulator"},
                        )
                    ),
                    SimpleNamespace(metadata=SimpleNamespace(name="unrelated-service", labels={})),
                    SimpleNamespace(metadata=SimpleNamespace(name="btc-node-old-service", labels={})),
                ]
            ),
            delete_namespaced_pod=lambda **kwargs: deleted_pods.append(cast(str, kwargs["name"])),
            delete_namespaced_service=lambda **kwargs: deleted_services.append(cast(str, kwargs["name"])),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                side_effect=[regular_client, cleanup_client],
            ),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            driver.port_forwards[("btc-node", 18443)] = FakeForward()
            driver.cleanup()

        self.assertEqual(closed_forwards, ["closed"])
        self.assertEqual(deleted_pods, ["wallet-helper", "btc-node-old"])
        self.assertEqual(deleted_services, ["wallet-helper-service", "btc-node-old-service"])

    def test_cleanup_deletes_owned_namespace_without_listing_resources(self) -> None:
        deleted_namespaces: list[str] = []

        cleanup_client = SimpleNamespace(
            delete_namespace=lambda **kwargs: deleted_namespaces.append(cast(str, kwargs["name"])),
            list_namespaced_pod=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("owned namespace cleanup should not list pods")
            ),
            list_namespaced_service=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("owned namespace cleanup should not list services")
            ),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=cleanup_client,
            ),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=False)
            driver.cleanup()

        self.assertEqual(deleted_namespaces, ["coinjoin-test"])
