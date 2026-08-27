import base64
import copy
import importlib.util
import io
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest import TestCase
from unittest.mock import Mock, patch

from manager.exceptions import CoinjoinEmulatorError, KubernetesResourceQuotaError
from tests.kubernetes_helpers import (
    FakePortForwardServer,
    load_kubernetes_symbols,
    run_driver_with_mapped_volume,
)

# pylint: disable=protected-access

if TYPE_CHECKING:

    from manager.driver.kubernetes_port_forward import PortForwardServer as PortForwardServerClass


class KubernetesDriverTest(TestCase):
    @patch("manager.driver.kubernetes.config.load_incluster_config")
    @patch("manager.driver.kubernetes.config.load_kube_config")
    def test_falls_back_to_incluster_auth(self, load_kube_config: Mock, load_incluster_config: Mock) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        from kubernetes.config.config_exception import ConfigException  # pylint: disable=import-outside-toplevel

        load_kube_config.side_effect = ConfigException("no kubeconfig")
        with patch.object(KubernetesDriver, "_new_client", return_value=Mock()):
            KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
        load_incluster_config.assert_called_once_with()

    def test_run_accepts_and_maps_docker_style_volumes(self) -> None:
        driver, pod_ip, ports, pod_bodies, service_bodies = run_driver_with_mapped_volume()
        self.assertEqual(pod_ip, "10.42.0.10")
        self.assertEqual(driver.control_host, "127.0.0.1")
        self.assertEqual(ports, {18443: 41000})
        self.assertEqual(len(FakePortForwardServer.started), 1)
        self.assertEqual(FakePortForwardServer.started[0].namespace, "coinjoin-test")
        self.assertEqual(FakePortForwardServer.started[0].pod_name, "btc-node")
        self.assertEqual(FakePortForwardServer.started[0].remote_port, 18443)
        service_spec = cast(dict[str, object], service_bodies[0]["spec"])
        service_ports = cast(list[dict[str, object]], service_spec["ports"])
        self.assertEqual(service_spec["type"], "ClusterIP")
        self.assertNotIn("nodePort", service_ports[0])
        service_metadata = cast(dict[str, object], service_bodies[0]["metadata"])
        service_labels = cast(dict[str, object], service_metadata["labels"])
        self.assertEqual(service_metadata["name"], "btc-node")
        self.assertEqual(service_labels["app.kubernetes.io/managed-by"], "coinjoin-emulator")

        pod_metadata = cast(dict[str, object], pod_bodies[0]["metadata"])
        pod_labels = cast(dict[str, object], pod_metadata["labels"])
        self.assertEqual(pod_labels["app.kubernetes.io/managed-by"], "coinjoin-emulator")
        pod_spec = cast(dict[str, object], pod_bodies[0]["spec"])
        containers = cast(list[dict[str, object]], pod_spec["containers"])
        container = containers[0]
        self.assertEqual(container["command"], ["./run.sh", "-blocksxor=0"])
        resources = cast(dict[str, object], container["resources"])
        limits = cast(dict[str, object], resources["limits"])
        requests = cast(dict[str, object], resources["requests"])
        self.assertEqual(limits["cpu"], 0.5)
        self.assertEqual(requests["cpu"], 0.1)
        self.assertEqual(limits["memory"], "768Mi")
        self.assertEqual(requests["memory"], "768Mi")
        security_context = cast(dict[str, object], container["securityContext"])
        self.assertEqual(security_context["runAsUser"], 1234)
        self.assertEqual(security_context["runAsGroup"], 5678)
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

    def test_run_keeps_wasabi_ports_out_of_the_pods_ephemeral_pool(self) -> None:
        _, _, _, pod_bodies, _ = run_driver_with_mapped_volume()

        pod_spec = cast(dict[str, object], pod_bodies[0]["spec"])
        pod_security_context = cast(dict[str, object], pod_spec["securityContext"])
        self.assertEqual(
            pod_security_context["sysctls"],
            [{"name": "net.ipv4.ip_local_reserved_ports", "value": "37127-37260"}],
        )

    def test_run_falls_back_when_the_api_server_forbids_the_sysctl(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        forbidden = self._api_error(
            403,
            '{"message":"pods \\"wasabi-coordinator\\" is forbidden: '
            'forbidden sysctl: \\"net.ipv4.ip_local_reserved_ports\\" not allowlisted"}',
        )
        pod_bodies: list[dict[str, object]] = []

        def create_pod(**kwargs: object) -> None:
            body = cast(dict[str, object], kwargs["body"])
            pod_bodies.append(copy.deepcopy(body))
            if len(pod_bodies) == 1:
                raise forbidden

        kube_client = SimpleNamespace(create_namespaced_pod=create_pod)

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch("manager.driver.kubernetes.client.CoreV1Api", return_value=kube_client),
        ):
            driver = KubernetesDriver(namespace="man5-ns", reuse_namespace=True)
            driver.run("wasabi-coordinator", "wasabi-coordinator:2.6.0", skip_ip=True)

        self.assertEqual(len(pod_bodies), 2)
        self.assertIn("securityContext", cast(dict[str, object], pod_bodies[0]["spec"]))
        self.assertNotIn("securityContext", cast(dict[str, object], pod_bodies[1]["spec"]))
        self.assertIn("wasabi-coordinator", driver.managed_pod_names)

    def test_run_recreates_the_pod_when_the_kubelet_forbids_the_sysctl(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        FakePortForwardServer.reset()
        pod_bodies: list[dict[str, object]] = []
        rejected = SimpleNamespace(
            spec=SimpleNamespace(node_name="node-1"),
            status=SimpleNamespace(
                pod_ip=None,
                phase="Failed",
                reason="SysctlForbidden",
                message="forbidden sysctl: net.ipv4.ip_local_reserved_ports",
                container_statuses=[],
            ),
        )
        started = SimpleNamespace(
            spec=SimpleNamespace(node_name="node-1"),
            status=SimpleNamespace(pod_ip="10.42.0.10", phase="Running", container_statuses=[]),
        )
        statuses = [rejected, started]

        kube_client = SimpleNamespace(
            create_namespaced_pod=lambda **kwargs: pod_bodies.append(
                copy.deepcopy(cast(dict[str, object], kwargs["body"]))
            ),
            read_namespaced_pod_status=lambda **_kwargs: statuses[min(len(pod_bodies), len(statuses)) - 1],
            delete_namespaced_pod=lambda **_kwargs: None,
            delete_namespaced_service=lambda **_kwargs: None,
            read_namespaced_pod=Mock(side_effect=self._not_found_error()),
            read_namespaced_service=Mock(side_effect=self._not_found_error()),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch("manager.driver.kubernetes.client.CoreV1Api", return_value=kube_client),
        ):
            driver = KubernetesDriver(namespace="man5-ns", reuse_namespace=True)
            pod_ip, _ = driver.run("wasabi-coordinator", "wasabi-coordinator:2.6.0", ports={})

        self.assertEqual(pod_ip, "10.42.0.10")
        self.assertEqual(len(pod_bodies), 2)
        self.assertNotIn("securityContext", cast(dict[str, object], pod_bodies[1]["spec"]))
        self.assertIn("wasabi-coordinator", driver.managed_pod_names)

    def test_run_labels_pods_and_services_with_run_id(self) -> None:
        _, _, _, pod_bodies, service_bodies = run_driver_with_mapped_volume(
            run_id="wasabi-run-1"
        )

        pod_labels = cast(
            dict[str, str],
            cast(dict[str, object], pod_bodies[0]["metadata"])["labels"],
        )
        service_labels = cast(
            dict[str, str],
            cast(dict[str, object], service_bodies[0]["metadata"])["labels"],
        )
        self.assertEqual(pod_labels["coinjoin.run-id"], "wasabi-run-1")
        self.assertEqual(service_labels["coinjoin.run-id"], "wasabi-run-1")

    def test_run_does_not_create_empty_service_when_no_ports_are_exposed(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
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

    def test_run_reports_cpu_quota_exhaustion_explicitly(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        quota_error = self._api_error(
            403,
            '{"message":"pods \\"wasabi-client-000\\" is forbidden: exceeded quota: '
            "default-cldp6, requested: limits.cpu=1, used: limits.cpu=31500m, "
            'limited: limits.cpu=32"}',
        )
        kube_client = SimpleNamespace(create_namespaced_pod=Mock(side_effect=quota_error))

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch("manager.driver.kubernetes.client.CoreV1Api", return_value=kube_client),
        ):
            driver = KubernetesDriver(namespace="man5-ns", reuse_namespace=True)
            with self.assertRaisesRegex(
                KubernetesResourceQuotaError,
                r"Kubernetes CPU quota exhausted.*wasabi-client-000.*man5-ns.*"
                r"default-cldp6.*limits\.cpu=1.*31500m.*limits\.cpu=32.*smaller scenario",
            ):
                driver.run("wasabi-client-000", "wasabi-client:2.6.0", skip_ip=True, cpu=1.0)

        self.assertNotIn("wasabi-client-000", driver.managed_pod_names)

    def test_run_preserves_non_quota_api_error(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        forbidden = self._api_error(403, '{"message":"pods are forbidden by policy"}')
        kube_client = SimpleNamespace(create_namespaced_pod=Mock(side_effect=forbidden))

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch("manager.driver.kubernetes.client.CoreV1Api", return_value=kube_client),
        ):
            driver = KubernetesDriver(namespace="man5-ns", reuse_namespace=True)
            with self.assertRaises(type(forbidden)):
                driver.run("wasabi-client-000", "wasabi-client:2.6.0", skip_ip=True, cpu=1.0)

    @staticmethod
    def _api_error(status: int, body: str = "") -> Exception:
        module = importlib.import_module("manager.driver.kubernetes")
        error = cast(Exception, module.ApiException())
        setattr(error, "status", status)
        setattr(error, "body", body)
        return error

    @classmethod
    def _not_found_error(cls) -> Exception:
        return cls._api_error(404)

    def test_stop_deletes_service_with_container_dns_name(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        deleted_pods: list[str] = []
        deleted_services: list[str] = []
        kube_client = SimpleNamespace(
            delete_namespaced_pod=lambda **kwargs: deleted_pods.append(cast(str, kwargs["name"])),
            delete_namespaced_service=lambda **kwargs: deleted_services.append(cast(str, kwargs["name"])),
            read_namespaced_pod=Mock(side_effect=self._not_found_error()),
            read_namespaced_service=Mock(side_effect=self._not_found_error()),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=kube_client,
            ),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            driver.stop("btc-node")

        self.assertEqual(deleted_pods, ["btc-node"])
        self.assertEqual(deleted_services, ["btc-node"])

    def test_stop_waits_until_pod_and_service_are_deleted(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        terminating_pod = SimpleNamespace(status=SimpleNamespace(phase="Terminating"))
        read_pod = Mock(side_effect=[terminating_pod, self._not_found_error()])
        read_service = Mock(side_effect=self._not_found_error())
        kube_client = SimpleNamespace(
            delete_namespaced_pod=Mock(),
            delete_namespaced_service=Mock(),
            read_namespaced_pod=read_pod,
            read_namespaced_service=read_service,
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=kube_client,
            ),
            patch("manager.driver.kubernetes.sleep"),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            driver.stop("wasabi-coordinator")

        self.assertEqual(read_pod.call_count, 2)
        read_service.assert_called_once()

    def test_stop_fails_when_pod_deletion_never_completes(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        stuck_pod = SimpleNamespace(status=SimpleNamespace(phase="Terminating"))
        kube_client = SimpleNamespace(
            delete_namespaced_pod=Mock(),
            delete_namespaced_service=Mock(),
            read_namespaced_pod=Mock(return_value=stuck_pod),
            read_namespaced_service=Mock(side_effect=self._not_found_error()),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=kube_client,
            ),
            patch("manager.driver.kubernetes.sleep"),
            patch("manager.driver.kubernetes.monotonic", side_effect=[0, 1, 130]),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            with self.assertRaisesRegex(CoinjoinEmulatorError, "still present at the .*s deletion deadline"):
                driver.stop("wasabi-coordinator")

    def test_stop_retries_transient_delete_api_error(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        delete_pod = Mock(side_effect=[self._api_error(500), None])
        kube_client = SimpleNamespace(
            delete_namespaced_pod=delete_pod,
            delete_namespaced_service=Mock(),
            read_namespaced_pod=Mock(side_effect=self._not_found_error()),
            read_namespaced_service=Mock(side_effect=self._not_found_error()),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=kube_client,
            ),
            patch("manager.driver.kubernetes.sleep"),
            patch("manager.driver.kubernetes.monotonic", side_effect=[0, 1, 2]),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            driver.stop("wasabi-coordinator")

        self.assertEqual(delete_pod.call_count, 2)

    def test_stop_raises_non_transient_delete_api_error_immediately(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        delete_service = Mock()
        read_pod = Mock()
        kube_client = SimpleNamespace(
            delete_namespaced_pod=Mock(side_effect=self._api_error(403)),
            delete_namespaced_service=delete_service,
            read_namespaced_pod=read_pod,
            read_namespaced_service=Mock(),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=kube_client,
            ),
            patch("manager.driver.kubernetes.monotonic", return_value=0),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            with self.assertRaisesRegex(CoinjoinEmulatorError, "Failed to delete Kubernetes pod.*API status 403"):
                driver.stop("wasabi-coordinator")

        delete_service.assert_not_called()
        read_pod.assert_not_called()

    def test_stop_retries_transient_deletion_status_read_error(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        read_pod = Mock(side_effect=[self._api_error(500), self._not_found_error()])
        kube_client = SimpleNamespace(
            delete_namespaced_pod=Mock(),
            delete_namespaced_service=Mock(),
            read_namespaced_pod=read_pod,
            read_namespaced_service=Mock(side_effect=self._not_found_error()),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=kube_client,
            ),
            patch("manager.driver.kubernetes.sleep"),
            patch("manager.driver.kubernetes.monotonic", side_effect=[0, 1, 2]),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            driver.stop("wasabi-coordinator")

        self.assertEqual(read_pod.call_count, 2)

    def test_stop_raises_non_transient_deletion_status_read_error_immediately(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        read_service = Mock()
        kube_client = SimpleNamespace(
            delete_namespaced_pod=Mock(),
            delete_namespaced_service=Mock(),
            read_namespaced_pod=Mock(side_effect=self._api_error(403)),
            read_namespaced_service=read_service,
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=kube_client,
            ),
            patch("manager.driver.kubernetes.monotonic", side_effect=[0, 1]),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            with self.assertRaisesRegex(
                CoinjoinEmulatorError, "Failed to verify deletion of Kubernetes pod.*API status 403"
            ):
                driver.stop("wasabi-coordinator")

        read_service.assert_not_called()

    def test_upload_reports_silent_remote_command_failure(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        response = Mock()
        response.is_open.side_effect = [True, False]
        response.peek_stdout.return_value = False
        response.peek_stderr.return_value = False
        response.returncode = 17
        kube_client = SimpleNamespace(
            connect_get_namespaced_pod_exec=object(),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=kube_client,
            ),
            patch("manager.driver.kubernetes.stream", return_value=response),
            TemporaryDirectory() as directory,
        ):
            source = Path(directory) / "Config.json"
            source.write_text("{}", encoding="utf-8")
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)

            with self.assertRaisesRegex(RuntimeError, "failed with exit code 17"):
                driver.upload(
                    "wasabi-client-000",
                    str(source),
                    "/root/.walletwasabi/client/Config.json",
                )

        response.close.assert_called_once_with()

    def test_upload_accepts_client_without_returncode_property(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()

        def successful_response() -> Mock:
            response = Mock(
                spec=[
                    "is_open",
                    "update",
                    "peek_stdout",
                    "read_stdout",
                    "peek_stderr",
                    "read_stderr",
                    "close",
                ]
            )
            response.is_open.side_effect = [True, False]
            response.peek_stdout.return_value = False
            response.peek_stderr.return_value = False
            return response

        responses = [successful_response(), successful_response()]
        kube_client = SimpleNamespace(connect_get_namespaced_pod_exec=object())

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch("manager.driver.kubernetes.client.CoreV1Api", return_value=kube_client),
            patch("manager.driver.kubernetes.stream", side_effect=responses) as stream_mock,
            TemporaryDirectory() as directory,
        ):
            source = Path(directory) / "Config.json"
            source.write_text("{}", encoding="utf-8")
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)

            driver.upload(
                "wasabi-client-000",
                str(source),
                "/root/.walletwasabi/client/Config.json",
            )

        self.assertEqual(stream_mock.call_count, 2)
        for response in responses:
            response.close.assert_called_once_with()

    def test_diagnostics_reports_missing_running_oomkilled_and_evicted_pods(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()

        def state(**kwargs: object) -> SimpleNamespace:
            values: dict[str, object] = {"terminated": None, "waiting": None, "running": None}
            values.update(kwargs)
            return SimpleNamespace(**values)

        def pod(
            name: str,
            phase: str,
            reason: str | None = None,
            container_state: SimpleNamespace | None = None,
            last_state: SimpleNamespace | None = None,
        ) -> SimpleNamespace:
            return SimpleNamespace(
                metadata=SimpleNamespace(name=name),
                status=SimpleNamespace(
                    phase=phase,
                    reason=reason,
                    message=None,
                    init_container_statuses=[],
                    container_statuses=[
                        SimpleNamespace(
                            name=name,
                            ready=phase == "Running",
                            restart_count=1 if last_state else 0,
                            state=container_state or state(running=SimpleNamespace(started_at="now")),
                            last_state=last_state or state(),
                        )
                    ],
                ),
            )

        running = pod("wasabi-client-000", "Running")
        oomkilled = pod(
            "wasabi-client-001",
            "Running",
            last_state=state(
                terminated=SimpleNamespace(
                    reason="OOMKilled",
                    message=None,
                    exit_code=137,
                    signal=9,
                    started_at="before",
                    finished_at="after",
                )
            ),
        )
        evicted = pod("wasabi-client-003", "Failed", reason="Evicted")
        event = SimpleNamespace(
            event_time=None,
            last_timestamp="2026-07-06T17:45:00Z",
            first_timestamp=None,
            involved_object=SimpleNamespace(name="wasabi-client-002"),
            type="Warning",
            reason="NotFound",
            message="pod was deleted",
            count=1,
        )
        regular_client = Mock()
        diagnostics_client = SimpleNamespace(
            list_namespaced_pod=lambda **_kwargs: SimpleNamespace(items=[running, oomkilled, evicted]),
            read_namespaced_pod_log=lambda **kwargs: f"logs for {kwargs['name']}",
            list_namespaced_event=lambda **_kwargs: SimpleNamespace(items=[event]),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                side_effect=[regular_client, diagnostics_client],
            ),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            driver.managed_pod_names.update(
                {
                    "wasabi-client-000",
                    "wasabi-client-001",
                    "wasabi-client-002",
                    "wasabi-client-003",
                }
            )
            diagnostics = driver.diagnostics()

        self.assertIn("pod wasabi-client-000: phase=Running", diagnostics)
        self.assertIn("reason=OOMKilled", diagnostics)
        self.assertIn("pod wasabi-client-002: NotFound", diagnostics)
        self.assertIn("pod wasabi-client-003: phase=Failed, reason=Evicted", diagnostics)
        self.assertIn("Warning wasabi-client-002: NotFound: pod was deleted", diagnostics)

    def test_cleanup_uses_fresh_client_and_deletes_managed_resources(self) -> None:
        KubernetesDriver, PortForwardServer = load_kubernetes_symbols()
        closed_forwards: list[str] = []
        deleted_pods: list[str] = []
        deleted_services: list[str] = []
        fake_forward = Mock(spec=PortForwardServer)
        fake_forward.close.side_effect = lambda: closed_forwards.append("closed")

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
            driver.port_forwards[("btc-node", 18443)] = cast("PortForwardServerClass", fake_forward)
            driver.cleanup()

        self.assertEqual(closed_forwards, ["closed"])
        self.assertEqual(deleted_pods, ["wallet-helper"])
        self.assertEqual(deleted_services, ["wallet-helper-service"])

    def test_cleanup_deletes_owned_namespace_without_listing_resources(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
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

    def test_wait_for_pod_ip_reports_scheduling_failure_when_pod_never_lands(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        pending_pod = SimpleNamespace(
            spec=SimpleNamespace(node_name=None),
            status=SimpleNamespace(pod_ip=None, phase="Pending", container_statuses=[]),
        )
        kube_client = SimpleNamespace(
            read_namespaced_pod_status=lambda **_kwargs: pending_pod,
            list_namespaced_event=lambda **_kwargs: SimpleNamespace(
                items=[
                    SimpleNamespace(
                        reason="FailedScheduling",
                        message="0/53 nodes are available: 44 Insufficient cpu.",
                        last_timestamp="2026-07-19T20:58:41Z",
                    )
                ]
            ),
        )

        clock = iter([0.0, 0.0, 0.0, 1.0, 5.0, 5.0])

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch("manager.driver.kubernetes.client.CoreV1Api", return_value=kube_client),
            patch("manager.driver.kubernetes.sleep"),
            patch("manager.driver.kubernetes.monotonic", side_effect=lambda: next(clock)),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            with self.assertRaises(CoinjoinEmulatorError) as caught:
                driver._wait_for_pod_ip("btc-node", timeout_seconds=2)

        message = str(caught.exception)
        self.assertIn("was not scheduled onto any node", message)
        self.assertIn("Insufficient cpu", message)

    def test_download_refuses_unscheduled_pod_instead_of_exec(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        pending_pod = SimpleNamespace(
            spec=SimpleNamespace(node_name=None),
            status=SimpleNamespace(pod_ip=None, phase="Pending", container_statuses=[]),
        )
        kube_client = SimpleNamespace(
            read_namespaced_pod_status=lambda **_kwargs: pending_pod,
            list_namespaced_event=lambda **_kwargs: SimpleNamespace(items=[]),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch("manager.driver.kubernetes.client.CoreV1Api", return_value=kube_client),
            patch(
                "manager.driver.kubernetes.stream",
                side_effect=AssertionError("download must not exec into an unscheduled pod"),
            ),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            with self.assertRaises(RuntimeError) as caught:
                driver.download("btc-node", "/home/bitcoin/data/", "/tmp/out")

        self.assertIn("never scheduled onto a node", str(caught.exception))

    def test_download_refuses_pod_whose_container_already_exited(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        finished_pod = SimpleNamespace(
            spec=SimpleNamespace(node_name="node-1"),
            status=SimpleNamespace(pod_ip="10.42.2.5", phase="Succeeded", container_statuses=[]),
        )
        kube_client = SimpleNamespace(
            read_namespaced_pod_status=lambda **_kwargs: finished_pod,
            list_namespaced_event=lambda **_kwargs: SimpleNamespace(items=[]),
        )

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch("manager.driver.kubernetes.client.CoreV1Api", return_value=kube_client),
            patch(
                "manager.driver.kubernetes.stream",
                side_effect=AssertionError("download must not exec into a terminated container"),
            ),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            with self.assertRaises(RuntimeError) as caught:
                driver.download("wasabi-coordinator", "/home/wasabi/.walletwasabi/coordinator/", "/tmp/out")

        self.assertIn("phase Succeeded", str(caught.exception))

    @staticmethod
    def _running_pod_client() -> SimpleNamespace:
        running_pod = SimpleNamespace(
            spec=SimpleNamespace(node_name="node-1"),
            status=SimpleNamespace(pod_ip="10.42.0.10", phase="Running", container_statuses=[]),
        )
        return SimpleNamespace(
            read_namespaced_pod_status=lambda **_kwargs: running_pod,
            list_namespaced_event=lambda **_kwargs: SimpleNamespace(items=[]),
            connect_get_namespaced_pod_exec=lambda *_args, **_kwargs: None,
        )

    @staticmethod
    def _exec_response(encoded: str, stderr: str) -> SimpleNamespace:
        state = {"open": True}
        payload = {"stdout": encoded, "stderr": stderr}

        def read(channel: str) -> str:
            value = payload[channel]
            payload[channel] = ""
            return value

        def update(**_kwargs: object) -> None:
            state["open"] = False

        return SimpleNamespace(
            is_open=lambda: state["open"],
            update=update,
            peek_stdout=lambda: payload["stdout"],
            peek_stderr=lambda: payload["stderr"],
            read_stdout=lambda: read("stdout"),
            read_stderr=lambda: read("stderr"),
            close=lambda: state.update(open=False),
        )

    def _download_with_stderr(self, stderr: str, destination: str) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            entry = tarfile.TarInfo("joinmarket/logs/J538RQdrjQFBGwP1.log")
            content = b"path: m/84'/1'/0'/0/3, address: bcrt1qexample\n"
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
        encoded = base64.b64encode(buffer.getvalue()).decode()

        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=self._running_pod_client(),
            ),
            patch(
                "manager.driver.kubernetes.stream",
                return_value=self._exec_response(encoded, stderr),
            ),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            driver.download("jcs-009", "/home/joinmarket", destination)

    def test_download_keeps_archive_when_a_live_log_changes_while_it_is_read(self) -> None:
        # A JoinMarket client keeps writing while its logs are archived; discarding
        # the whole download for that warning left the run without the client's logs
        # and made every coin of that wallet unattributable during analysis.
        with TemporaryDirectory() as destination:
            self._download_with_stderr(
                "tar: joinmarket/.joinmarket/logs/J538RQdrjQFBGwP1.log: "
                "file changed as we read it\n",
                destination,
            )
            stored = Path(destination) / "joinmarket" / "logs" / "J538RQdrjQFBGwP1.log"
            self.assertTrue(stored.is_file())
            self.assertIn("address: bcrt1qexample", stored.read_text())

    def test_download_still_fails_on_a_real_tar_error(self) -> None:
        with TemporaryDirectory() as destination:
            with self.assertRaises(RuntimeError) as caught:
                self._download_with_stderr(
                    "tar: /home/joinmarket: Cannot open: No such file or directory\n",
                    destination,
                )
        self.assertIn("Cannot open", str(caught.exception))

    def test_download_fails_when_the_archive_is_empty(self) -> None:
        KubernetesDriver, _ = load_kubernetes_symbols()
        with (
            patch("manager.driver.kubernetes.config.load_kube_config"),
            patch(
                "manager.driver.kubernetes.client.CoreV1Api",
                return_value=self._running_pod_client(),
            ),
            patch(
                "manager.driver.kubernetes.stream",
                return_value=self._exec_response("", "tar: a.log: file changed as we read it\n"),
            ),
        ):
            driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
            with self.assertRaises(RuntimeError) as caught:
                driver.download("jcs-009", "/home/joinmarket", "/tmp/out")

        self.assertIn("empty archive", str(caught.exception))
