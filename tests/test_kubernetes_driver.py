import sys
import types
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

try:
    import kubernetes  # noqa: F401
except ModuleNotFoundError:
    kubernetes_module = types.ModuleType("kubernetes")
    client_module = types.ModuleType("kubernetes.client")
    config_module = types.ModuleType("kubernetes.config")
    stream_module = types.ModuleType("kubernetes.stream")
    exceptions_module = types.ModuleType("kubernetes.client.exceptions")

    class ApiException(Exception):
        pass

    client_module.CoreV1Api = object
    client_module.V1DeleteOptions = object
    config_module.load_kube_config = lambda: None
    stream_module.stream = lambda *args, **kwargs: None
    exceptions_module.ApiException = ApiException

    kubernetes_module.client = client_module
    kubernetes_module.config = config_module

    sys.modules["kubernetes"] = kubernetes_module
    sys.modules["kubernetes.client"] = client_module
    sys.modules["kubernetes.config"] = config_module
    sys.modules["kubernetes.stream"] = stream_module
    sys.modules["kubernetes.client.exceptions"] = exceptions_module

from manager.driver.kubernetes import KubernetesDriver


class KubernetesDriverTest(TestCase):
    def test_run_accepts_and_maps_docker_style_volumes(self):
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
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            pod_bodies = []

            def create_pod(**kwargs):
                pod_bodies.append(kwargs["body"])

            kube_client.create_namespaced_pod = create_pod

            pod_ip, ports = driver.run(
                "btc-node",
                "btc-node:latest",
                ports={18443: 18443},
                volumes={
                    "/tmp/btc-data": {
                        "bind": "/home/bitcoin/data",
                        "mode": "rw",
                    }
                },
            )

        self.assertEqual(pod_ip, "10.42.0.10")
        self.assertEqual(ports, {18443: 31843})

        pod_spec = pod_bodies[0]["spec"]
        container = pod_spec["containers"][0]
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
