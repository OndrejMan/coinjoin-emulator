import base64
import os
import re
import shlex
import tarfile
import time
import traceback
import uuid
from functools import cached_property
from io import BytesIO
from threading import RLock
from time import sleep

import backoff
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream

from manager.exceptions import KubernetesResourceQuotaError, StartupError

from . import RESERVED_PORT_RANGE, RESERVED_PORTS_SYSCTL, Driver

POD_IP_WAIT_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_POD_IP_TIMEOUT", "1800"))
DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_DOWNLOAD_TIMEOUT", "1800"))
UPLOAD_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_UPLOAD_TIMEOUT", "120"))
UPLOAD_COMMAND_CHUNK_SIZE = 16 * 1024
BENIGN_TAR_WARNING_RE = re.compile(
    r"^tar: .*: (file changed as we read it|socket ignored)$"
    r"|^tar: Removing leading [`'\"]?/[`'\"]? from (member names|hard link targets)$"
)
MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "coinjoin-emulator"


def _strip_reserved_ports_sysctl(pod_manifest):
    """Remove the reserved-port sysctl when a cluster does not allow it."""
    spec = pod_manifest.get("spec") or {}
    security_context = spec.get("securityContext") or {}
    sysctls = security_context.get("sysctls") or []
    remaining = [sysctl for sysctl in sysctls if sysctl.get("name") != RESERVED_PORTS_SYSCTL]
    if len(remaining) == len(sysctls):
        return False
    if remaining:
        security_context["sysctls"] = remaining
    else:
        spec.pop("securityContext", None)
    return True


def _is_sysctl_rejection(error):
    return getattr(error, "status", None) in {400, 403, 422} and "sysctl" in str(
        getattr(error, "body", "") or error
    ).lower()


def _split_tar_diagnostics(stderr):
    """Separate warnings that leave a complete archive from real tar errors."""
    benign, fatal = [], []
    for line in stderr.splitlines():
        if line.strip():
            (benign if BENIGN_TAR_WARNING_RE.match(line.strip()) else fatal).append(line.strip())
    return benign, fatal


class KubernetesDriver(Driver):
    def __init__(self, namespace="coinjoin", reuse_namespace=False, pull_secret_path=None, in_cluster=False,
                 run_id=None):

        if in_cluster:
            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()
        else:
            config.load_kube_config()

        self.client = client.CoreV1Api()
        self._namespace = namespace
        self.reuse_namespace = reuse_namespace
        self.pull_secret_path = pull_secret_path
        self.in_cluster = in_cluster
        self.run_id = run_id

    @cached_property
    def _exec_lock(self):
        """Serialize exec calls that temporarily swap the shared ApiClient request method.

        kubernetes.stream.stream mutates the API client while a connection is
        open, so concurrent artifact downloads otherwise cross their websocket
        streams and corrupt the archive payload.
        """
        return RLock()

    def _create_image_pull_secret(self):
        secret_name = "regcred"
        try:
            with open(self.pull_secret_path, "r") as f:
                dockerconfigjson = f.read()
            dockerconfigjson_b64 = base64.b64encode(dockerconfigjson.encode("utf-8")).decode("utf-8")

            secret = client.V1Secret(
                metadata=client.V1ObjectMeta(name=secret_name),
                data={
                    ".dockerconfigjson": dockerconfigjson_b64
                },
                type="kubernetes.io/dockerconfigjson",
            )
            # Try to create, if exists, replace
            try:
                self.client.create_namespaced_secret(namespace=self._namespace, body=secret)
                print(f"Created image pull secret {secret_name}")
            except ApiException as e:
                if e.status == 409:  # Already exists
                    self.client.replace_namespaced_secret(secret_name, self._namespace, secret)
                    print(f"Replaced image pull secret {secret_name}")
                else:
                    raise
        except Exception as e:
            print(f"Failed to create image pull secret: {e}")

    def create_namespace(self):
        namespace_manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": self._namespace},
        }
        self.client.create_namespace(body=namespace_manifest)

        @backoff.on_exception(backoff.constant, Exception, interval=5, max_time=30)
        def wait_for_active():
            ns = self.client.read_namespace(self._namespace)
            if ns.status.phase != "Active":
                print(f"Namespace '{self._namespace}' is not Active yet.")
                raise Exception(f"Namespace '{self._namespace}' not Active yet.")
            print(f"Namespace '{self._namespace}' is Active.")

        wait_for_active()

    @cached_property
    def namespace(self):
        if not self.reuse_namespace:
            self.create_namespace()
            if self.pull_secret_path:
                self._create_image_pull_secret()
        return self._namespace

    def has_image(self, name):
        return True

    def build(self, name, path):
        pass

    def pull(self, name):
        pass

    def resource_labels(self, name):
        """Label every resource so cleanup can find exactly this emulator's own."""
        labels = {"app": name, MANAGED_BY_LABEL: MANAGED_BY_VALUE}
        if self.run_id:
            labels["coinjoin.run-id"] = self.run_id
        return labels

    def build_pod_manifest(self, name, image, env, ports, cpu, memory,
                            user_id=None, volumes=None, command=None, group_id=None):
        if ports is None:
            ports = {}
        if env is None:
            env = {}

        volume_mounts = []
        pod_volumes = []
        for index, (host_path, mount) in enumerate((volumes or {}).items()):
            volume_name = f"host-volume-{index}"
            volume_mounts.append({
                "name": volume_name,
                "mountPath": mount["bind"],
                "readOnly": mount.get("mode") == "ro",
            })
            pod_volumes.append({
                "name": volume_name,
                "hostPath": {"path": host_path, "type": "DirectoryOrCreate"},
            })

        security_context = {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        } if user_id is None else {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                            "runAsUser": user_id,
                            "runAsGroup": user_id if group_id is None else group_id,
                        }

        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "labels": self.resource_labels(name)},
            "spec": {
                "restartPolicy": "Never",
                "containers": [
                    {
                        "image": image,
                        # CI pulls immutable registry images. A local k3d test imports an
                        # explicitly named image and opts into IfNotPresent so Kubernetes
                        # does not replace it with the registry tag.
                        "imagePullPolicy": os.environ.get("KUBERNETES_IMAGE_PULL_POLICY", "Always"),
                        "name": name,
                        "ports": [
                            {"containerPort": container_port}
                            for container_port in ports.keys()
                        ],
                        "env": [
                            {"name": k, "value": v}
                            for k, v in env.items()
                        ],
                        "volumeMounts": volume_mounts,
                        "securityContext": security_context,
                        "resources": {
                            "limits": {"cpu": cpu*1.5, "memory": f"{memory*1.5}Mi"},
                            "requests": {"cpu": cpu, "memory": f"{memory}Mi"},
                        },
                        # Keep the image ENTRYPOINT unless the caller overrides it
                        **({"command": command} if command is not None else {}),
                    }
                ],
                "volumes": pod_volumes,
                "securityContext": {
                    "sysctls": [{"name": RESERVED_PORTS_SYSCTL, "value": RESERVED_PORT_RANGE}]
                },
                # Add imagePullSecrets if pull_secret_path is set
                **({"imagePullSecrets": [{"name": "regcred"}]} if self.pull_secret_path else {}),
            },
        }

    def run(
        self,
        name,
        image,
        env=None,
        ports=None,
        cpu=None,
        memory=None,
        run_as_user=None,
        **kwargs
    ):
        pod_manifest = self.build_pod_manifest(
            name, image, env, ports, cpu, memory, run_as_user,
            kwargs.get("volumes"), kwargs.get("command"), kwargs.get("run_as_group"),
        )
        self._create_pod(name, pod_manifest)

        try:
            pod_ip = self._wait_for_pod_ip(name)
        except StartupError as error:
            # Not every kubelet allows the reserved-port sysctl; the run is
            # still valid without it, only more exposed to a port collision.
            if "SysctlForbidden" not in str(error) or not _strip_reserved_ports_sysctl(pod_manifest):
                raise
            print(f"[WARNING] kubelet forbade {RESERVED_PORTS_SYSCTL} for pod {name}; recreating it without it")
            self.stop(name)
            self._create_pod(name, pod_manifest)
            pod_ip = self._wait_for_pod_ip(name)
        except Exception as e:
            print(f"Failed to get pod IP: {e}")
            raise

        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": f"{name}", "labels": self.resource_labels(name)},
            "spec": {
                "type": "NodePort",
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
        try:
            resp = self.client.create_namespaced_service(
                body=service_manifest, namespace=self.namespace
            )
        except Exception as e:
            print(f"Failed to create service: {e}")
            raise

        if self.in_cluster:
            # For in-cluster: return service DNS name, original port mapping, no route
            port_mapping = {target_port: container_port for target_port, container_port in ports.items()}
            service_dns_name = f"{name}.{self.namespace}.svc.cluster.local"
            return service_dns_name, port_mapping, None
        else:
            # For external: return pod IP, node port mapping, no route (existing behavior)
            port_mapping = dict(
                map(lambda x: (x.target_port, x.node_port), resp.spec.ports)
            )
            return pod_ip or "", port_mapping, None

    def _create_pod(self, name, pod_manifest):
        try:
            self.client.create_namespaced_pod(body=pod_manifest, namespace=self.namespace)
            return
        except ApiException as error:
            details = str(getattr(error, "body", "") or error)
            if error.status == 403 and "exceeded quota" in details.lower():
                raise KubernetesResourceQuotaError(
                    f"Kubernetes quota rejected pod {name} in namespace {self.namespace}: {details}"
                ) from error
            if not _is_sysctl_rejection(error) or not _strip_reserved_ports_sysctl(pod_manifest):
                raise
            print(f"[WARNING] cluster rejected {RESERVED_PORTS_SYSCTL} for pod {name}; starting it without it")
        self.client.create_namespaced_pod(body=pod_manifest, namespace=self.namespace)

    def _wait_for_pod_ip(self, name):
        """Wait for a scheduled pod's IP, giving up on a terminal pod or a deadline."""
        deadline = time.monotonic() + POD_IP_WAIT_TIMEOUT_SECONDS
        while True:
            status = self.client.read_namespaced_pod_status(name=name, namespace=self.namespace).status
            if status.pod_ip:
                return status.pod_ip
            if status.phase in {"Failed", "Succeeded"}:
                detail = " ".join(
                    str(value) for value in (status.reason, status.message) if value
                )
                raise StartupError(
                    f"Pod {name} entered terminal phase {status.phase} before receiving an IP"
                    + (f": {detail}" if detail else "")
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Pod {name} did not receive an IP within {POD_IP_WAIT_TIMEOUT_SECONDS}s "
                    f"(last phase: {status.phase})"
                )
            sleep(1)

    def stop(self, name):
        try:
            self.client.delete_namespaced_pod(name=name, namespace=self.namespace)
            self.client.delete_namespaced_service(
                name, namespace=self.namespace
            )
        except Exception:
            pass

    def download(self, name, src_path, dst_path):
        self._require_exec_ready(name)
        if src_path[-1] == "/":
            src_path = src_path[:-1]
        src_parent, src_target = os.path.split(src_path)
        # The websocket carries text frames that may split at any byte, so the
        # archive is transported as one uninterrupted base64 stream (GNU base64
        # wraps its output by default) and decoded strictly below.
        exec_command = [
            "sh",
            "-c",
            f"tar cf - -C {shlex.quote(src_parent)} {shlex.quote(src_target)} | base64 | tr -d '\\n'",
        ]
        encoded_chunks = []
        stderr_chunks = []
        deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SECONDS
        with self._exec_lock:
            resp = self._exec_stream(name, exec_command, f"download {src_path}")
            while resp.is_open():
                if time.monotonic() >= deadline:
                    resp.close()
                    raise TimeoutError(f"Timed out downloading {name}:{src_path}")
                resp.update(timeout=1)
                if resp.peek_stdout():
                    encoded_chunks.append(resp.read_stdout())
                if resp.peek_stderr():
                    stderr_chunks.append(resp.read_stderr())
            resp.close()

        benign_warnings, fatal_errors = _split_tar_diagnostics("".join(stderr_chunks))
        if fatal_errors:
            raise RuntimeError("download command wrote stderr: " + "\n".join(fatal_errors))
        encoded = "".join(encoded_chunks)
        if not encoded.strip():
            detail = "; ".join(benign_warnings) or "no output"
            raise RuntimeError(f"download of {name}:{src_path} produced an empty archive: {detail}")
        if benign_warnings:
            print(
                f"[WARNING] {name}:{src_path} changed while it was archived; "
                f"keeping the completed archive: {'; '.join(benign_warnings)}"
            )
        try:
            payload = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise RuntimeError(f"download of {name}:{src_path} returned invalid base64") from error
        with tarfile.open(fileobj=BytesIO(payload)) as tar:
            tar.extractall(dst_path)

    def peek(self, name, path):
        self._require_exec_ready(name)
        output = ""
        with self._exec_lock:
            resp = self._exec_stream(name, ["cat", path], f"read {path}")
            while resp.is_open():
                resp.update(timeout=1)
                if resp.peek_stdout():
                    output += resp.read_stdout()
            resp.close()
        return output

    def _require_exec_ready(self, name):
        """Reject a pod whose container cannot service a Kubernetes exec request."""
        pod = self.client.read_namespaced_pod_status(name=name, namespace=self.namespace)
        if not getattr(getattr(pod, "spec", None), "node_name", None):
            raise RuntimeError(f"pod {name} was never scheduled onto a node, so nothing can be read from it")
        phase = getattr(getattr(pod, "status", None), "phase", None)
        if phase != "Running":
            raise RuntimeError(f"pod {name} is in phase {phase}, so its container is gone")

    def _exec_stream(self, name, exec_command, action):
        """Open an exec stream and turn a Kubernetes API failure into a clear error."""
        try:
            return stream(
                self.client.connect_get_namespaced_pod_exec,
                name,
                self.namespace,
                command=exec_command,
                stderr=True,
                stdin=True,
                stdout=True,
                tty=False,
                _preload_content=False,
            )
        except ApiException as error:
            raise RuntimeError(f"could not {action} on pod {name}: {error}") from error

    def get_pod_resource_usage(self, name):
        """
        Get memory usage of a pod by reading /proc/self/status.
        Returns dict with memory_mb and memory_limit_mb, or None if failed.
        """
        try:
            # Read process memory info from /proc
            output = ""
            with self._exec_lock:
                resp = self._exec_stream(name, ["cat", "/proc/self/status"], "read /proc/self/status")
                while resp.is_open():
                    resp.update(timeout=1)
                    if resp.peek_stdout():
                        output += resp.read_stdout()
                resp.close()

            # Parse VmRSS (Resident Set Size - actual RAM used)
            memory_kb = None
            for line in output.split('\n'):
                if line.startswith('VmRSS:'):
                    # Format: "VmRSS:      123456 kB"
                    parts = line.split()
                    if len(parts) >= 2:
                        memory_kb = int(parts[1])
                        break

            if memory_kb is None:
                return None

            # Get pod spec to find memory limit
            pod = self.client.read_namespaced_pod(name=name, namespace=self.namespace)
            memory_limit_str = pod.spec.containers[0].resources.limits.get('memory', '0Mi')
            # Parse memory limit (e.g., "128Mi" -> 128)
            memory_limit_mb = int(memory_limit_str.replace('Mi', '').replace('Gi', '000'))

            return {
                'memory_mb': memory_kb / 1024,
                'memory_limit_mb': memory_limit_mb,
                'memory_percent': (memory_kb / 1024 / memory_limit_mb * 100) if memory_limit_mb > 0 else 0
            }
        except Exception:
            # Silently fail - pod might be terminating
            return None

    def upload(self, name, src_path, dst_path):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w:tar") as tar:
            tar.add(src_path, arcname=dst_path)
        # write_stdin() truncated the archive whenever it exceeded a websocket
        # frame, and the loop exited before the remote tar had finished, so the
        # payload is staged in text chunks and unpacked with a checked command.
        payload = base64.b64encode(buf.getvalue()).decode("ascii")
        remote_payload = f"/tmp/coinjoin-emulator-upload-{uuid.uuid4().hex}.b64"
        deadline = time.monotonic() + UPLOAD_TIMEOUT_SECONDS

        try:
            for offset in range(0, len(payload), UPLOAD_COMMAND_CHUNK_SIZE):
                chunk = payload[offset:offset + UPLOAD_COMMAND_CHUNK_SIZE]
                redirect = ">" if offset == 0 else ">>"
                self._exec_checked(
                    name, dst_path, deadline,
                    ["sh", "-c", f'printf "%s" "$1" {redirect} "$2"', "sh", chunk, remote_payload],
                )
            self._exec_checked(
                name, dst_path, deadline,
                [
                    "sh", "-c",
                    'base64 -d "$1" | tar xf - -C /; status=$?; rm -f -- "$1"; exit "$status"',
                    "sh", remote_payload,
                ],
            )
        except Exception:
            try:
                self._exec_checked(name, dst_path, deadline, ["rm", "-f", "--", remote_payload])
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            raise

    def _exec_checked(self, name, dst_path, deadline, exec_command):
        """Run one upload command and fail if it wrote to stderr or exited non-zero."""
        stderr_chunks = []
        with self._exec_lock:
            resp = self._exec_stream(name, exec_command, f"upload to {dst_path}")
            while resp.is_open():
                if time.monotonic() >= deadline:
                    resp.close()
                    raise TimeoutError(f"Timed out uploading to {name}:{dst_path}")
                resp.update(timeout=1)
                if resp.peek_stdout():
                    resp.read_stdout()
                if resp.peek_stderr():
                    stderr_chunks.append(resp.read_stderr())
            returncode = getattr(resp, "returncode", None)
            resp.close()
        stderr = "".join(stderr_chunks).strip()
        if returncode not in (None, 0) or stderr:
            raise RuntimeError(f"upload to {name}:{dst_path} failed" + (f": {stderr}" if stderr else ""))


    def cleanup(self, image_prefix=""):
        # without this, the cleaunup fails because of open websocket channel from log gathering
        # but when the fresh client is created, the log gathering fails...
        # "Working" config is letting the cleanup fail and restarting it after run...
        # fresh_client = client.CoreV1Api()
        # self.client = fresh_client
        # return

        # Match on the label the driver stamps instead of guessing from names:
        # the name list missed pods and could delete a resource this run does
        # not own in a shared namespace.
        managed = f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}"
        try:
            pods = self.client.list_namespaced_pod(namespace=self._namespace, label_selector=managed)
        except ApiException as e:
            print("Error listing pods:", e)
            traceback.print_exc()
            print("Cleanup failed")
            return

        for pod in pods.items:
            try:
                print(f"Deleting pod {pod.metadata.name}")
                self.client.delete_namespaced_pod(name=pod.metadata.name, namespace=self._namespace)
            except ApiException:
                pass
        services = self.client.list_namespaced_service(namespace=self._namespace, label_selector=managed)
        for service in services.items:
            try:
                print("Deleting service", service.metadata.name)
                self.client.delete_namespaced_service(name=service.metadata.name, namespace=self._namespace)
            except ApiException:
                pass

        if not self.reuse_namespace:
            try:
                print(f"Deleting namespace {self._namespace}")
                self.client.delete_namespace(
                    name=self._namespace, body=client.V1DeleteOptions()
                )
            except ApiException:
                pass
