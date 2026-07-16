import importlib.util
import socket
import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest import TestCase
from unittest.mock import Mock, patch

from manager.exceptions import CoinjoinEmulatorError

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api as CoreV1ApiClass

    from manager.driver.kubernetes import KubernetesDriver as KubernetesDriverClass
    from manager.driver.kubernetes import PortForwardServer as PortForwardServerClass


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


def _load_kubernetes_symbols() -> tuple[type["KubernetesDriverClass"], type["PortForwardServerClass"]]:
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


def _capture_service_body(
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


def _run_driver_with_mapped_volume(
) -> tuple["KubernetesDriverClass", str, dict[int, int], list[dict[str, object]], list[dict[str, object]]]:
    KubernetesDriver, _ = _load_kubernetes_symbols()
    FakePortForwardServer.reset()
    pod_bodies: list[dict[str, object]] = []
    service_bodies: list[dict[str, object]] = []
    kube_client = SimpleNamespace(
        create_namespaced_pod=lambda **kwargs: pod_bodies.append(cast(dict[str, object], kwargs["body"])),
        read_namespaced_pod_status=lambda **kwargs: SimpleNamespace(
            status=SimpleNamespace(pod_ip="10.42.0.10")
        ),
        create_namespaced_service=lambda **kwargs: _capture_service_body(
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
        driver = KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
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


class KubernetesDriverTest(TestCase):
    @patch("manager.driver.kubernetes.config.load_incluster_config")
    @patch("manager.driver.kubernetes.config.load_kube_config")
    def test_falls_back_to_incluster_auth(
        self, load_kube_config: Mock, load_incluster_config: Mock
    ) -> None:
        KubernetesDriver, _ = _load_kubernetes_symbols()
        from kubernetes.config.config_exception import ConfigException  # pylint: disable=import-outside-toplevel

        load_kube_config.side_effect = ConfigException("no kubeconfig")
        with patch.object(KubernetesDriver, "_new_client", return_value=Mock()):
            KubernetesDriver(namespace="coinjoin-test", reuse_namespace=True)
        load_incluster_config.assert_called_once_with()

    def test_port_forward_retries_transient_handshake_failure(self) -> None:
        _, PortForwardServer = _load_kubernetes_symbols()

        class FakeForward:
            closed = False

            def socket(self, remote_port: int) -> object:
                return {"remote_port": remote_port}

            def close(self) -> None:
                self.closed = True

        fake_kube_client = cast(
            "CoreV1ApiClass",
            SimpleNamespace(connect_get_namespaced_pod_portforward=object()),
        )
        server = PortForwardServer(fake_kube_client, "coinjoin-test", "wasabi-client-005", 37128)
        self.addCleanup(server.close)
        client_socket = Mock(spec=socket.socket)
        fake_forward = FakeForward()
        bridge_calls: list[tuple[object, object]] = []

        def bridge(client_socket_obj: object, upstream_socket: object) -> None:
            bridge_calls.append((client_socket_obj, upstream_socket))

        with (
            patch.object(server, "bridge", side_effect=bridge),
            patch(
                "manager.driver.kubernetes.portforward",
                side_effect=[RuntimeError("Handshake status 502 Bad Gateway"), fake_forward],
            ) as portforward,
            patch("manager.driver.kubernetes.sleep"),
        ):
            server.handle_connection(cast(socket.socket, client_socket))

        self.assertEqual(portforward.call_count, 2)
        self.assertEqual(bridge_calls, [(client_socket, {"remote_port": 37128})])
        client_socket.close.assert_called_once_with()
        self.assertTrue(fake_forward.closed)

    def test_run_accepts_and_maps_docker_style_volumes(self) -> None:
        driver, pod_ip, ports, pod_bodies, service_bodies = _run_driver_with_mapped_volume()
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

    def test_run_does_not_create_empty_service_when_no_ports_are_exposed(self) -> None:
        KubernetesDriver, _ = _load_kubernetes_symbols()
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

    @staticmethod
    def _api_error(status: int) -> Exception:
        module = importlib.import_module("manager.driver.kubernetes")
        error = cast(Exception, module.ApiException())
        setattr(error, "status", status)
        return error

    @classmethod
    def _not_found_error(cls) -> Exception:
        return cls._api_error(404)

    def test_stop_deletes_service_with_container_dns_name(self) -> None:
        KubernetesDriver, _ = _load_kubernetes_symbols()
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
        KubernetesDriver, _ = _load_kubernetes_symbols()
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
        KubernetesDriver, _ = _load_kubernetes_symbols()
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
            with self.assertRaisesRegex(
                CoinjoinEmulatorError, "still present at the .*s deletion deadline"
            ):
                driver.stop("wasabi-coordinator")

    def test_stop_retries_transient_delete_api_error(self) -> None:
        KubernetesDriver, _ = _load_kubernetes_symbols()
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
        KubernetesDriver, _ = _load_kubernetes_symbols()
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
            with self.assertRaisesRegex(
                CoinjoinEmulatorError, "Failed to delete Kubernetes pod.*API status 403"
            ):
                driver.stop("wasabi-coordinator")

        delete_service.assert_not_called()
        read_pod.assert_not_called()

    def test_stop_retries_transient_deletion_status_read_error(self) -> None:
        KubernetesDriver, _ = _load_kubernetes_symbols()
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
        KubernetesDriver, _ = _load_kubernetes_symbols()
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
        KubernetesDriver, _ = _load_kubernetes_symbols()
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
        KubernetesDriver, _ = _load_kubernetes_symbols()

        def successful_response() -> Mock:
            response = Mock(spec=[
                "is_open",
                "update",
                "peek_stdout",
                "read_stdout",
                "peek_stderr",
                "read_stderr",
                "close",
            ])
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
        KubernetesDriver, _ = _load_kubernetes_symbols()

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
            list_namespaced_pod=lambda **_kwargs: SimpleNamespace(
                items=[running, oomkilled, evicted]
            ),
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
        KubernetesDriver, PortForwardServer = _load_kubernetes_symbols()
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
        KubernetesDriver, _ = _load_kubernetes_symbols()
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
