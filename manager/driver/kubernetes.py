import base64
import os
import re
import select
import shlex
import socket
import tarfile
import threading
import uuid
from functools import cached_property
from io import BytesIO
from time import monotonic, sleep
from typing import Protocol, cast

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.client.models.core_v1_event import CoreV1Event  # type: ignore[import-untyped]
from kubernetes.client.models.v1_pod import V1Pod  # type: ignore[import-untyped]
from kubernetes.config.config_exception import ConfigException
from kubernetes.stream import portforward, stream

from manager import log_output as log
from manager.exceptions import CoinjoinEmulatorError, KubernetesResourceQuotaError, StartupError

from . import Driver, extract_tar

MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "coinjoin-emulator"
MANAGED_LABELS = {
    MANAGED_BY_LABEL: MANAGED_BY_VALUE,
    "app.kubernetes.io/component": "emulator",
}
PORT_FORWARD_ATTEMPTS = 3
PORT_FORWARD_RETRY_DELAY_SECONDS = 0.25
# Shared clusters routinely leave pods Pending for tens of minutes while CPU frees up,
# so this budget covers scheduling queue time, not just container startup.
POD_IP_WAIT_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_POD_IP_TIMEOUT", "1800"))
POD_IP_WAIT_PROGRESS_LOG_SECONDS = 60
DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_DOWNLOAD_TIMEOUT", "1800"))
PEEK_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_PEEK_TIMEOUT", "60"))
UPLOAD_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_UPLOAD_TIMEOUT", "120"))
UPLOAD_COMMAND_CHUNK_SIZE = 16 * 1024
NAMESPACE_CREATE_RETRY_SECONDS = 60
POD_IP_TRANSIENT_API_STATUSES = {408, 409, 429, 500, 502, 503, 504}
RESOURCE_DELETE_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_DELETE_TIMEOUT", "120"))
RESOURCE_DELETE_TRANSIENT_API_STATUSES = {408, 409, 429, 500, 502, 503, 504}
CPU_QUOTA_RE = re.compile(
    r"exceeded quota:\s*(?P<quota>[^,]+),\s*"
    r"requested:\s*(?P<requested>.*?),\s*"
    r"used:\s*(?P<used>.*?),\s*"
    r"limited:\s*(?P<limited>[^\"}\r\n]+)",
    re.IGNORECASE,
)


def _raise_explicit_quota_error(error: ApiException, *, pod_name: str, namespace: str) -> None:
    """Translate a Kubernetes CPU-quota rejection into an actionable failure."""
    details = str(getattr(error, "body", "") or error)
    lowered = details.lower()
    if getattr(error, "status", None) != 403 or "exceeded quota" not in lowered:
        return
    if "limits.cpu" not in lowered and "requests.cpu" not in lowered:
        return

    match = CPU_QUOTA_RE.search(details)
    if match:
        quota_details = (
            f"quota '{match.group('quota').strip()}' rejected "
            f"{match.group('requested').strip()} "
            f"(used {match.group('used').strip()}; limit {match.group('limited').strip()})"
        )
    else:
        quota_details = details.strip()

    raise KubernetesResourceQuotaError(
        f"Kubernetes CPU quota exhausted while creating pod '{pod_name}' in namespace "
        f"'{namespace}': {quota_details}. Use a smaller scenario, reduce pod CPU limits, "
        "delete unused workloads, or request a larger namespace CPU quota."
    ) from error


class SocketLike(Protocol):
    def recv(self, size: int) -> bytes: ...
    def sendall(self, data: bytes) -> None: ...
    def fileno(self) -> int: ...


class PodListLike(Protocol):
    items: list[V1Pod]


class EventListLike(Protocol):
    items: list[CoreV1Event]


class ResourceReader(Protocol):
    def __call__(self, name: str, namespace: str) -> object: ...


class ResourceReadClient(Protocol):
    def read_namespaced_pod(self, name: str, namespace: str) -> object: ...

    def read_namespaced_service(self, name: str, namespace: str) -> object: ...


class DiagnosticsClient(Protocol):
    def list_namespaced_pod(self, namespace: str) -> PodListLike: ...

    def read_namespaced_pod_log(
        self,
        name: str,
        namespace: str,
        container: str,
        tail_lines: int,
        timestamps: bool,
    ) -> str: ...

    def list_namespaced_event(
        self,
        namespace: str,
        field_selector: str | None = None,
    ) -> EventListLike: ...


class PortForwardServer:
    def __init__(self, kube_client: client.CoreV1Api, namespace: str, pod_name: str, remote_port: int) -> None:
        self.kube_client = kube_client
        self.namespace = namespace
        self.pod_name = pod_name
        self.remote_port = remote_port
        self.closed = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.local_port = int(self.listener.getsockname()[1])
        self.thread = threading.Thread(
            name=f"kubernetes-port-forward-{pod_name}-{remote_port}",
            target=self.serve,
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.closed.set()
        try:
            self.listener.close()
        except OSError:
            pass

    def serve(self) -> None:
        while not self.closed.is_set():
            try:
                client_socket, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(
                name=f"kubernetes-port-forward-connection-{self.pod_name}-{self.remote_port}",
                target=self.handle_connection,
                args=(client_socket,),
                daemon=True,
            ).start()

    def handle_connection(self, client_socket: socket.socket) -> None:
        forward = None
        try:
            for attempt in range(PORT_FORWARD_ATTEMPTS):
                try:
                    forward = portforward(
                        self.kube_client.connect_get_namespaced_pod_portforward,
                        self.pod_name,
                        self.namespace,
                        ports=str(self.remote_port),
                    )
                    break
                except Exception as error:  # pylint: disable=broad-exception-caught
                    log.debug(
                        f"- port-forward {self.pod_name}:{self.remote_port} failed "
                        f"({attempt + 1}/{PORT_FORWARD_ATTEMPTS}): {error}"
                    )
                    if attempt + 1 >= PORT_FORWARD_ATTEMPTS:
                        raise
                    sleep(PORT_FORWARD_RETRY_DELAY_SECONDS)
            if forward is None:
                return
            upstream_socket = forward.socket(self.remote_port)
            self.bridge(client_socket, upstream_socket)
        except Exception as error:  # pylint: disable=broad-exception-caught # pragma: no cover - defensive logging around background thread
            log.debug(f"- port-forward {self.pod_name}:{self.remote_port} failed: {error}")
        finally:
            try:
                client_socket.close()
            except OSError:
                pass
            if forward is not None:
                forward.close()

    def bridge(self, client_socket: SocketLike, upstream_socket: SocketLike) -> None:
        sockets = [client_socket, upstream_socket]
        while not self.closed.is_set():
            try:
                readable, _, _ = select.select(sockets, [], [], 0.5)
            except OSError:
                return
            for source in readable:
                target = upstream_socket if source is client_socket else client_socket
                try:
                    data = source.recv(65536)
                    if not data:
                        return
                    target.sendall(data)
                except OSError:
                    return


class KubernetesDriver(Driver):
    def __init__(self, namespace: str = "coinjoin", reuse_namespace: bool = False, port_forward: bool = True) -> None:
        try:
            config.load_kube_config()
        except ConfigException:
            getattr(config, "load_incluster_config")()
        self.client = self._new_client()
        self._namespace = namespace
        self.reuse_namespace = reuse_namespace
        self.control_host = "127.0.0.1"
        self.port_forwards: dict[tuple[str, int], PortForwardServer] = {}
        self.port_forward_enabled = port_forward
        # Without port-forwarding the manager must reach pods at their pod IP
        # and container port (it runs inside the cluster, or behind a proxy).
        self.direct_network = not port_forward
        self.managed_pod_names: set[str] = set()

    def _new_client(self) -> client.CoreV1Api:
        return client.CoreV1Api()

    @cached_property
    def namespace(self) -> str:
        namespace_manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": self._namespace},
        }
        if not self.reuse_namespace:
            # A previous run's namespace may still be terminating; retry while
            # the API answers 409 Conflict for the same name.
            deadline = monotonic() + NAMESPACE_CREATE_RETRY_SECONDS
            while True:
                try:
                    self.client.create_namespace(body=namespace_manifest)
                    break
                except ApiException as error:
                    if getattr(error, "status", None) != 409 or monotonic() >= deadline:
                        raise
                    log.warning(f"- namespace {self._namespace} still exists (terminating?); retrying")
                    sleep(2)
        return self._namespace

    def has_image(self, name: str) -> bool:
        return True

    def build(self, name: str, path: str) -> None:
        pass

    def pull(self, name: str) -> None:
        pass

    def run(
        self,
        name: str,
        image: str,
        env: dict[str, str | None] | None = None,
        ports: dict[int, int] | None = None,
        skip_ip: bool = False,
        cpu: float = 0.1,
        memory: int = 768,
        cpu_request: float | None = None,
        memory_request: int | None = None,
        volumes: dict[str, dict[str, str]] | None = None,
        command: list[str] | None = None,
    ) -> tuple[str, dict[int, int]]:
        if ports is None:
            ports = {}
        if env is None:
            env = {}
        volume_mounts = []
        pod_volumes = []
        storage_uid = None
        storage_gid = None
        for index, (host_path, mount) in enumerate((volumes or {}).items()):
            volume_name = f"host-volume-{index}"
            volume_mounts.append(
                {
                    "name": volume_name,
                    "mountPath": mount["bind"],
                    "readOnly": mount.get("mode") == "ro",
                }
            )
            pod_volumes.append(
                {
                    "name": volume_name,
                    "hostPath": {
                        "path": host_path,
                        "type": "DirectoryOrCreate",
                    },
                }
            )
            if mount.get("uid") is not None:
                candidate_uid = int(mount["uid"])
                if storage_uid is not None and storage_uid != candidate_uid:
                    raise ValueError("Kubernetes volume mounts require one runAsUser value")
                storage_uid = candidate_uid
            if mount.get("gid") is not None:
                candidate_gid = int(mount["gid"])
                if storage_gid is not None and storage_gid != candidate_gid:
                    raise ValueError("Kubernetes volume mounts require one runAsGroup value")
                storage_gid = candidate_gid

        security_context: dict[str, object] = {
            "allowPrivilegeEscalation": False,
            "capabilities": {
                "drop": ["ALL"],
            },
            "runAsNonRoot": True,
            "seccompProfile": {
                "type": "RuntimeDefault",
            },
        }
        if storage_uid is not None:
            security_context["runAsUser"] = storage_uid
        if storage_gid is not None:
            security_context["runAsGroup"] = storage_gid

        container_spec: dict[str, object] = {
            "image": image,
            "imagePullPolicy": "Always",
            "name": name,
            "ports": [
                {
                    "containerPort": container_port,
                }
                for container_port in ports.keys()
            ],
            "env": [
                {
                    "name": k,
                    "value": v,
                }
                for k, v in env.items()
            ],
            "volumeMounts": volume_mounts,
            "securityContext": security_context,
            "resources": {
                "limits": {
                    "cpu": cpu,
                    "memory": f"{memory}Mi",
                },
                "requests": {
                    "cpu": cpu if cpu_request is None else cpu_request,
                    "memory": f"{memory if memory_request is None else memory_request}Mi",
                },
            },
        }
        if command is not None:
            container_spec["command"] = command

        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "labels": {"app": name, **MANAGED_LABELS}},
            "spec": {
                "restartPolicy": "Never",
                "containers": [container_spec],
                "volumes": pod_volumes,
            },
        }

        try:
            resp = self.client.create_namespaced_pod(body=pod_manifest, namespace=self.namespace)
        except ApiException as error:
            _raise_explicit_quota_error(error, pod_name=name, namespace=self.namespace)
            raise
        self.managed_pod_names.add(name)

        pod_ip = ""
        if not skip_ip:
            pod_ip = self._wait_for_pod_ip(name)

        if not ports:
            return pod_ip, {}

        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            # Keep the service name identical to the Docker/Podman container
            # name. Emulator images use these stable names for in-cluster DNS
            # (for example, JoinMarket connects to ``btc-node`` and
            # ``irc-server``).
            "metadata": {"name": name, "labels": {"app": name, **MANAGED_LABELS}},
            "spec": {
                # Pod access from the external manager is handled through the
                # Kubernetes port-forward API. ClusterIP is sufficient for
                # stable in-cluster DNS without reserving host NodePorts.
                "type": "ClusterIP",
                "selector": {"app": name},
                "ports": [
                    {
                        "name": f"{name}-{container_port}",
                        "protocol": "TCP",
                        "port": container_port,
                        "targetPort": target_port,
                    }
                    for (target_port, container_port) in ports.items()
                ],
            },
        }

        resp = self.client.create_namespaced_service(body=service_manifest, namespace=self.namespace)
        if self.port_forward_enabled:
            port_mapping = self.start_port_forwards(
                name,
                [int(port.target_port) for port in resp.spec.ports],
            )
        else:
            port_mapping = {}
        return pod_ip, port_mapping

    @staticmethod
    def _pod_status_detail(pod: V1Pod) -> str:
        status = pod.status
        details = [
            f"phase={getattr(status, 'phase', None) or 'Unknown'}",
            f"reason={getattr(status, 'reason', None) or '-'}",
            f"message={getattr(status, 'message', None) or '-'}",
        ]
        for container_status in [
            *(getattr(status, "init_container_statuses", None) or []),
            *(getattr(status, "container_statuses", None) or []),
        ]:
            details.append(
                f"{container_status.name}: {KubernetesDriver._container_state_summary(container_status.state)}"
            )
        return "; ".join(details)

    def _wait_for_pod_ip(self, name: str, timeout_seconds: int = POD_IP_WAIT_TIMEOUT_SECONDS) -> str:
        deadline = monotonic() + timeout_seconds
        last_status = "not read yet"
        next_progress_log = monotonic() + POD_IP_WAIT_PROGRESS_LOG_SECONDS
        scheduled = False
        while monotonic() < deadline:
            try:
                pod = self.client.read_namespaced_pod_status(name=name, namespace=self.namespace)
            except ApiException as error:
                if getattr(error, "status", None) in POD_IP_TRANSIENT_API_STATUSES:
                    log.warning(f"- transient Kubernetes API error while waiting for pod {name}: {error}")
                    sleep(1)
                    continue
                raise StartupError(f"Could not read Kubernetes pod {name} status: {error}") from error
            status = pod.status
            last_status = self._pod_status_detail(pod)
            if status.pod_ip:
                return str(status.pod_ip)
            if getattr(status, "phase", None) in {"Failed", "Succeeded"}:
                raise StartupError(f"Kubernetes pod {name} ended before it got an IP: {last_status}")
            container_statuses = [
                *(getattr(status, "init_container_statuses", None) or []),
                *(getattr(status, "container_statuses", None) or []),
            ]
            waiting_reasons = {
                getattr(container_status.state.waiting, "reason", "")
                for container_status in container_statuses
                if getattr(getattr(container_status, "state", None), "waiting", None) is not None
            }
            fatal_waiting = {
                "CreateContainerConfigError",
                "CreateContainerError",
                "ErrImagePull",
                "ImagePullBackOff",
                "InvalidImageName",
            }
            if waiting_reasons & fatal_waiting:
                raise StartupError(f"Kubernetes pod {name} cannot start: {last_status}")
            scheduled = bool(getattr(getattr(pod, "spec", None), "node_name", None))
            if monotonic() >= next_progress_log:
                remaining = int(deadline - monotonic())
                stage = "starting" if scheduled else "waiting to be scheduled"
                log.warning(
                    f"- pod {name} still {stage} ({remaining}s of {timeout_seconds}s left): "
                    f"{self._pending_reason(name) or last_status}"
                )
                next_progress_log = monotonic() + POD_IP_WAIT_PROGRESS_LOG_SECONDS
            sleep(1)
        if not scheduled:
            raise StartupError(
                f"Kubernetes pod {name} was not scheduled onto any node within "
                f"{timeout_seconds} seconds (cluster has no room for it): "
                f"{self._pending_reason(name) or last_status}. "
                "Retry when the cluster has free capacity, lower the pod's CPU request, "
                "or raise COINJOIN_K8S_POD_IP_TIMEOUT."
            )
        raise StartupError(f"Kubernetes pod {name} did not get an IP within {timeout_seconds} seconds: {last_status}")

    def _pending_reason(self, name: str) -> str:
        """Return the newest scheduler complaint for a pod, e.g. the FailedScheduling message."""
        events_client = cast(DiagnosticsClient, self.client)
        try:
            events = events_client.list_namespaced_event(
                namespace=self.namespace,
                field_selector=f"involvedObject.name={name}",
            ).items
        except ApiException:
            return ""
        scheduling = [event for event in events if getattr(event, "reason", None) in {"FailedScheduling", "Preempting"}]
        if not scheduling:
            return ""
        newest = max(
            scheduling,
            key=lambda event: str(
                getattr(event, "event_time", None)
                or getattr(event, "last_timestamp", None)
                or getattr(event, "first_timestamp", None)
                or ""
            ),
        )
        return f"{getattr(newest, 'reason', '')}: {getattr(newest, 'message', '')}".strip()

    def start_port_forwards(self, name: str, ports: list[int]) -> dict[int, int]:
        port_mapping = {}
        for remote_port in ports:
            forward = PortForwardServer(self._new_client(), self.namespace, name, remote_port)
            forward.start()
            self.port_forwards[(name, remote_port)] = forward
            port_mapping[remote_port] = forward.local_port
            log.info(f"- forwarding {name}:{remote_port} to 127.0.0.1:{forward.local_port}")
        return port_mapping

    def close_port_forwards(self, name: str | None = None) -> None:
        for key, forward in list(self.port_forwards.items()):
            if name is not None and key[0] != name:
                continue
            forward.close()
            del self.port_forwards[key]

    def stop(self, name: str) -> None:
        self.close_port_forwards(name)
        deadline = monotonic() + RESOURCE_DELETE_TIMEOUT_SECONDS
        self._delete_resource(
            "pod",
            name,
            deadline,
        )
        self._delete_resource(
            "service",
            name,
            deadline,
        )
        self._wait_removed(name, deadline=deadline)
        self.managed_pod_names.discard(name)

    def _delete_resource(
        self,
        resource_kind: str,
        name: str,
        deadline: float,
    ) -> None:
        while True:
            try:
                if resource_kind == "pod":
                    self.client.delete_namespaced_pod(name=name, namespace=self._namespace)
                elif resource_kind == "service":
                    self.client.delete_namespaced_service(name=name, namespace=self._namespace)
                else:
                    raise ValueError(f"Unsupported Kubernetes resource kind: {resource_kind}")
                return
            except ApiException as error:
                status = getattr(error, "status", None)
                if status == 404:
                    return
                if status not in RESOURCE_DELETE_TRANSIENT_API_STATUSES:
                    raise CoinjoinEmulatorError(
                        f"Failed to delete Kubernetes {resource_kind} {name}: API status {status}: {error}"
                    ) from error
                if monotonic() >= deadline:
                    raise CoinjoinEmulatorError(
                        f"Timed out deleting Kubernetes {resource_kind} {name} after "
                        f"{RESOURCE_DELETE_TIMEOUT_SECONDS}s (last API status: {status})"
                    ) from error
                log.warning(
                    f"- transient Kubernetes API status {status} while deleting {resource_kind} {name}; retrying"
                )
                sleep(1)

    def _wait_removed(
        self,
        name: str,
        timeout: int = RESOURCE_DELETE_TIMEOUT_SECONDS,
        *,
        deadline: float | None = None,
    ) -> None:
        """Block until the pod and service are gone.

        Kubernetes deletes asynchronously; recreating the same name while the
        old resources are still terminating fails with a 409 conflict.
        """
        # The generated Kubernetes client accepts these methods dynamically,
        # while its bundled type information does not expose their full surface.
        reader_client = cast(ResourceReadClient, self.client)
        if deadline is None:
            deadline = monotonic() + timeout
        while monotonic() < deadline:
            if self._resource_gone(reader_client.read_namespaced_pod, "pod", name) and self._resource_gone(
                reader_client.read_namespaced_service, "service", name
            ):
                return
            sleep(1)
        raise CoinjoinEmulatorError(
            f"Kubernetes pod/service {name} was still present at the {timeout}s deletion deadline"
        )

    def _resource_gone(self, reader: ResourceReader, resource_kind: str, name: str) -> bool:
        try:
            reader(name=name, namespace=self._namespace)
        except ApiException as error:
            status = getattr(error, "status", None)
            if status == 404:
                return True
            if status in RESOURCE_DELETE_TRANSIENT_API_STATUSES:
                log.warning(
                    f"- transient Kubernetes API status {status} while checking deletion "
                    f"of {resource_kind} {name}; retrying"
                )
                return False
            raise CoinjoinEmulatorError(
                f"Failed to verify deletion of Kubernetes {resource_kind} {name}: API status {status}: {error}"
            ) from error
        return False

    @staticmethod
    def _container_state_summary(state: object) -> str:
        for state_name in ("terminated", "waiting", "running"):
            value = getattr(state, state_name, None)
            if value is None:
                continue
            details = []
            for attribute in ("reason", "message", "exit_code", "signal", "started_at", "finished_at"):
                item = getattr(value, attribute, None)
                if item is not None and item != "":
                    details.append(f"{attribute}={item}")
            return f"{state_name}" + (f" ({', '.join(details)})" if details else "")
        return "unknown"

    def diagnostics(self) -> str:
        lines = [f"Kubernetes diagnostics for namespace {self._namespace}:"]
        # The generated Kubernetes client accepts these methods dynamically,
        # while its bundled type information does not expose their full surface.
        diagnostics_client = cast(DiagnosticsClient, self._new_client())
        try:
            pods = diagnostics_client.list_namespaced_pod(namespace=self._namespace).items
        except Exception as error:  # pylint: disable=broad-exception-caught
            lines.append(f"- unable to list pods: {error}")
            pods = []

        present_names = {pod.metadata.name for pod in pods if getattr(getattr(pod, "metadata", None), "name", None)}
        for missing_name in sorted(self.managed_pod_names - present_names):
            lines.append(f"- pod {missing_name}: NotFound")

        for pod in sorted(pods, key=lambda item: item.metadata.name or ""):
            name = pod.metadata.name or "<unknown>"
            status = pod.status
            lines.append(
                f"- pod {name}: phase={status.phase or 'Unknown'}, "
                f"reason={status.reason or '-'}, message={status.message or '-'}"
            )
            container_statuses = [
                *(status.init_container_statuses or []),
                *(status.container_statuses or []),
            ]
            for container_status in container_statuses:
                lines.append(
                    f"  container {container_status.name}: ready={container_status.ready}, "
                    f"restarts={container_status.restart_count}, "
                    f"state={self._container_state_summary(container_status.state)}, "
                    f"last_state={self._container_state_summary(container_status.last_state)}"
                )
                try:
                    pod_logs = diagnostics_client.read_namespaced_pod_log(
                        name=name,
                        namespace=self._namespace,
                        container=container_status.name,
                        tail_lines=200,
                        timestamps=True,
                    )
                except Exception as error:  # pylint: disable=broad-exception-caught
                    lines.append(f"  {container_status.name} logs unavailable: {error}")
                else:
                    if pod_logs:
                        lines.append(f"  last 200 log lines for {container_status.name}:")
                        lines.extend(f"    {line}" for line in str(pod_logs).splitlines())

        try:
            events = diagnostics_client.list_namespaced_event(namespace=self._namespace).items
        except Exception as error:  # pylint: disable=broad-exception-caught
            lines.append(f"- unable to list events: {error}")
        else:
            lines.append("- namespace events:")
            for event in sorted(
                events,
                key=lambda item: str(
                    getattr(item, "event_time", None)
                    or getattr(item, "last_timestamp", None)
                    or getattr(item, "first_timestamp", None)
                    or ""
                ),
            ):
                involved = getattr(event, "involved_object", None)
                resource = getattr(involved, "name", None) or "<unknown>"
                event_type = getattr(event, "type", None) or "Unknown"
                reason = getattr(event, "reason", None) or "Unknown"
                message = getattr(event, "message", None) or ""
                count = getattr(event, "count", None) or 1
                lines.append(f"  {event_type} {resource}: {reason}: {message} (count={count})")
        return "\n".join(lines)

    def _require_exec_ready(self, name: str) -> None:
        """Fail with the real reason instead of an exec websocket 400 on an unusable pod."""
        try:
            pod = self.client.read_namespaced_pod_status(name=name, namespace=self.namespace)
        except ApiException as error:
            raise RuntimeError(f"pod {name} is unavailable: {error}") from error
        if not getattr(getattr(pod, "spec", None), "node_name", None):
            reason = self._pending_reason(name) or self._pod_status_detail(pod)
            raise RuntimeError(
                f"pod {name} was never scheduled onto a node, so there is nothing to download from it: {reason}"
            )
        phase = getattr(getattr(pod, "status", None), "phase", None)
        if phase not in {"Running", "Succeeded"}:
            raise RuntimeError(f"pod {name} is in phase {phase}, not Running/Succeeded: {self._pod_status_detail(pod)}")

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        self._require_exec_ready(name)
        if src_path[-1] == "/":
            src_path = src_path[:-1]
        src_parent, src_target = os.path.split(src_path)
        exec_command = [
            "sh",
            "-c",
            f"tar cf - -C {shlex.quote(src_parent)} {shlex.quote(src_target)} | base64",
        ]
        resp = stream(
            self._new_client().connect_get_namespaced_pod_exec,
            name,
            self.namespace,
            command=exec_command,
            stderr=True,
            stdin=True,
            stdout=True,
            tty=False,
            _preload_content=False,
        )

        encoded_chunks: list[str] = []
        stderr_chunks: list[str] = []
        deadline = monotonic() + DOWNLOAD_TIMEOUT_SECONDS
        while resp.is_open():
            if monotonic() >= deadline:
                resp.close()
                raise TimeoutError(f"Timed out downloading {name}:{src_path}")
            resp.update(timeout=1)
            if resp.peek_stdout():
                encoded_chunks.append(resp.read_stdout())
            if resp.peek_stderr():
                stderr_chunks.append(resp.read_stderr())
        stderr = "".join(stderr_chunks)
        if stderr.strip():
            raise RuntimeError(f"download command wrote stderr: {stderr.strip()}")
        fo = BytesIO(base64.b64decode("".join(encoded_chunks)))
        with tarfile.open(fileobj=fo) as tar:
            extract_tar(tar, dst_path)
        resp.close()

    def peek(self, name: str, path: str, *, missing_ok: bool = False) -> str:
        exec_command = ["sh", "-c", 'if [ -f "$1" ]; then cat -- "$1"; fi', "sh", path] if missing_ok else ["cat", path]
        resp = stream(
            self._new_client().connect_get_namespaced_pod_exec,
            name,
            self.namespace,
            command=exec_command,
            stderr=True,
            stdin=True,
            stdout=True,
            tty=False,
            _preload_content=False,
        )

        output_chunks: list[str] = []
        stderr_chunks: list[str] = []
        deadline = monotonic() + PEEK_TIMEOUT_SECONDS
        while resp.is_open():
            if monotonic() >= deadline:
                resp.close()
                raise TimeoutError(f"Timed out reading {name}:{path}")
            resp.update(timeout=1)
            if resp.peek_stdout():
                output_chunks.append(resp.read_stdout())
            if resp.peek_stderr():
                stderr_chunks.append(resp.read_stderr())
        resp.close()
        stderr = "".join(stderr_chunks)
        if stderr.strip():
            raise RuntimeError(f"peek of {name}:{path} wrote stderr: {stderr.strip()}")
        return "".join(output_chunks)

    def logs(self, name: str) -> str:
        return self.client.read_namespaced_pod_log(name=name, namespace=self.namespace)

    def upload(self, name: str, src_path: str, dst_path: str) -> None:
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w:tar") as tar:
            tar.add(src_path, arcname=dst_path)
        payload = base64.b64encode(buf.getvalue()).decode("ascii")
        remote_payload = f"/tmp/coinjoin-emulator-upload-{uuid.uuid4().hex}.b64"
        deadline = monotonic() + UPLOAD_TIMEOUT_SECONDS

        def exec_checked(exec_command: list[str]) -> None:
            resp = stream(
                self._new_client().connect_get_namespaced_pod_exec,
                name,
                self.namespace,
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,
            )
            stderr_chunks: list[str] = []
            while resp.is_open():
                if monotonic() >= deadline:
                    resp.close()
                    raise TimeoutError(f"Timed out uploading {src_path} to {name}:{dst_path}")
                resp.update(timeout=1)
                if resp.peek_stdout():
                    log.debug(f"STDOUT: {resp.read_stdout()}")
                if resp.peek_stderr():
                    stderr_chunks.append(resp.read_stderr())
            # Older kubernetes-client WSClient versions do not expose a
            # returncode. In that case stderr remains the available failure
            # signal; do not turn a successful command into exit code None.
            returncode = getattr(resp, "returncode", None)
            resp.close()
            stderr = "".join(stderr_chunks)
            if returncode not in (None, 0):
                details = f": {stderr.strip()}" if stderr.strip() else ""
                raise RuntimeError(f"upload to {name}:{dst_path} failed with exit code {returncode}{details}")
            if stderr.strip():
                raise RuntimeError(f"upload to {name}:{dst_path} wrote stderr: {stderr.strip()}")

        try:
            for offset in range(0, len(payload), UPLOAD_COMMAND_CHUNK_SIZE):
                chunk = payload[offset : offset + UPLOAD_COMMAND_CHUNK_SIZE]
                redirect = ">" if offset == 0 else ">>"
                exec_checked(
                    [
                        "sh",
                        "-c",
                        f'printf "%s" "$1" {redirect} "$2"',
                        "sh",
                        chunk,
                        remote_payload,
                    ]
                )
            exec_checked(
                [
                    "sh",
                    "-c",
                    'base64 -d "$1" | tar xf - -C /; status=$?; rm -f -- "$1"; exit "$status"',
                    "sh",
                    remote_payload,
                ]
            )
        except Exception:
            try:
                exec_checked(["rm", "-f", "--", remote_payload])
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            raise

    def cleanup(self, image_prefix: str = "") -> None:
        self.close_port_forwards()
        cleanup_client = self._new_client()
        if not self.reuse_namespace:
            try:
                cleanup_client.delete_namespace(name=self._namespace, body=client.V1DeleteOptions())
            except ApiException as error:
                if getattr(error, "status", None) != 404:
                    raise
            return

        pods = cleanup_client.list_namespaced_pod(namespace=self._namespace)
        for pod in pods.items:
            if self._is_managed_resource(pod):
                try:
                    cleanup_client.delete_namespaced_pod(name=pod.metadata.name, namespace=self._namespace)
                except ApiException:
                    pass
        services = cleanup_client.list_namespaced_service(namespace=self._namespace)
        for service in services.items:
            if self._is_managed_resource(service):
                try:
                    cleanup_client.delete_namespaced_service(name=service.metadata.name, namespace=self._namespace)
                except ApiException:
                    pass

    def _is_managed_resource(self, resource: object) -> bool:
        metadata = getattr(resource, "metadata", None)
        labels = getattr(metadata, "labels", None) or {}
        return labels.get(MANAGED_BY_LABEL) == MANAGED_BY_VALUE
