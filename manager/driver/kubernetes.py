import base64
import os
import shlex
import tarfile
import time
import traceback
import uuid
from functools import cached_property
from io import BytesIO
from time import sleep
from typing import cast

import backoff
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream

from manager.exceptions import CoinjoinEmulatorError, KubernetesResourceQuotaError, StartupError

from . import Driver

DEFAULT_CPU = 0.1
DEFAULT_MEMORY = 768
MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "coinjoin-emulator"
POD_IP_WAIT_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_POD_IP_TIMEOUT", "1800"))
UPLOAD_COMMAND_CHUNK_SIZE = 16 * 1024
UPLOAD_TIMEOUT_SECONDS = int(os.environ.get("COINJOIN_K8S_UPLOAD_TIMEOUT", "120"))


class KubernetesDriver(Driver):
    def __init__(
        self,
        namespace: str = "coinjoin",
        reuse_namespace: bool = False,
        pull_secret_path: str | None = None,
        in_cluster: bool = False,
        run_id: str | None = None,
    ) -> None:

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

    def _create_image_pull_secret(self) -> None:
        secret_name = "regcred"
        if not self.pull_secret_path:
            raise ValueError("pull_secret_path is not configured")
        try:
            with open(self.pull_secret_path, "r", encoding="utf-8") as f:
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

    def create_namespace(self) -> None:
        namespace_manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": self._namespace},
        }
        self.client.create_namespace(body=namespace_manifest)

        @backoff.on_exception(backoff.constant, Exception, interval=5, max_time=30)
        def wait_for_active() -> None:
            ns = self.client.read_namespace(self._namespace)
            if ns.status.phase != "Active":
                print(f"Namespace '{self._namespace}' is not Active yet.")
                raise CoinjoinEmulatorError(f"Namespace '{self._namespace}' not Active yet.")
            print(f"Namespace '{self._namespace}' is Active.")

        wait_for_active()

    @cached_property
    def namespace(self) -> str:
        if not self.reuse_namespace:
            self.create_namespace()
            if self.pull_secret_path:
                self._create_image_pull_secret()
        return self._namespace

    def has_image(self, name: str) -> bool:
        return True

    def build(self, name: str, path: str) -> None:
        pass

    def pull(self, name: str) -> None:
        pass

    def build_pod_manifest(
        self,
        name: str,
        image: str,
        env: dict[str, str] | None,
        ports: dict[int, int] | None,
        cpu: float | None,
        memory: int | None,
        user_id: int | None = None,
        volumes: dict[str, dict[str, str]] | None = None,
        command: list[str] | None = None,
    ) -> dict[str, object]:
        if cpu is None:
            cpu = DEFAULT_CPU
        if memory is None:
            memory = DEFAULT_MEMORY
        if ports is None:
            ports = {}
        if env is None:
            env = {}

        volume_mounts: list[dict[str, object]] = []
        pod_volumes: list[dict[str, object]] = []
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
                    "hostPath": {"path": host_path, "type": "DirectoryOrCreate"},
                }
            )

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
                            "runAsGroup": user_id,
                        }

        labels = {"app": name, MANAGED_BY_LABEL: MANAGED_BY_VALUE}
        if self.run_id:
            labels["coinjoin.run-id"] = self.run_id
        container: dict[str, object] = {
            "image": image,
            "imagePullPolicy": "Always",
            "name": name,
            "ports": [{"containerPort": container_port} for container_port in ports.keys()],
            "env": [{"name": k, "value": v} for k, v in env.items()],
            "volumeMounts": volume_mounts,
            "securityContext": security_context,
            "resources": {
                "limits": {"cpu": cpu * 1.5, "memory": f"{memory * 1.5}Mi"},
                "requests": {"cpu": cpu, "memory": f"{memory}Mi"},
            },
        }
        if command is not None:
            container["command"] = command

        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "labels": labels},
            "spec": {
                "restartPolicy": "Never",
                "containers": [container],
                "volumes": pod_volumes,
                # Add imagePullSecrets if pull_secret_path is set
                **({"imagePullSecrets": [{"name": "regcred"}]} if self.pull_secret_path else {}),
            },
        }

    def run(
        self,
        name: str,
        image: str,
        env: dict[str, str] | None = None,
        ports: dict[int, int] | None = None,
        cpu: float | None = None,
        memory: int | None = None,
        **kwargs: object,
    ) -> tuple[str, dict[int, int], object]:
        run_as_user = cast(int | None, kwargs.get("run_as_user"))
        volumes = cast(dict[str, dict[str, str]] | None, kwargs.get("volumes"))
        command = cast(list[str] | None, kwargs.get("command"))
        ports = ports or {}
        pod_manifest = self.build_pod_manifest(
            name, image, env, ports, cpu, memory, run_as_user, volumes, command
        )
        try:
            resp = self.client.create_namespaced_pod(body=pod_manifest, namespace=self.namespace)
        except ApiException as error:
            details = str(getattr(error, "body", "") or error)
            if error.status == 403 and "exceeded quota" in details.lower():
                raise KubernetesResourceQuotaError(
                    f"Kubernetes quota rejected pod {name} in namespace {self.namespace}: {details}"
                ) from error
            raise

        pod_ip = None
        deadline = time.monotonic() + POD_IP_WAIT_TIMEOUT_SECONDS
        try:
            while pod_ip is None:
                pod_status = self.client.read_namespaced_pod_status(
                    name=name, namespace=self.namespace
                ).status
                pod_ip = pod_status.pod_ip
                if pod_status.phase in {"Failed", "Succeeded"} and pod_ip is None:
                    raise StartupError(
                        f"Pod {name} entered terminal phase {pod_status.phase} before receiving an IP"
                    )
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Pod {name} did not receive an IP within {POD_IP_WAIT_TIMEOUT_SECONDS}s "
                        f"(last phase: {pod_status.phase})"
                    )
                sleep(1)
        except Exception as e:
            print(f"Failed to get pod IP: {e}")
            raise

        pod_metadata = cast(dict[str, object], pod_manifest["metadata"])
        managed_labels = cast(dict[str, str], pod_metadata["labels"])
        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": f"{name}", "labels": managed_labels},
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
            port_mapping = dict(ports.items())
            service_dns_name = f"{name}.{self.namespace}.svc.cluster.local"
            return service_dns_name, port_mapping, None
        # For external: return pod IP, node port mapping, no route (existing behavior)
        port_mapping = dict(
            map(lambda x: (x.target_port, x.node_port), resp.spec.ports)
        )
        return pod_ip or "", port_mapping, None

    def stop(self, name: str) -> None:
        try:
            self.client.delete_namespaced_pod(name=name, namespace=self.namespace)
            self.client.delete_namespaced_service(
                name, namespace=self.namespace
            )
        except Exception:
            pass

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        if src_path[-1] == "/":
            src_path = src_path[:-1]
        src_parent, src_target = os.path.split(src_path)
        exec_command = [
            "sh",
            "-c",
            f"tar cf - -C {shlex.quote(src_parent)} {shlex.quote(src_target)} | base64",
        ]
        resp = stream(
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
        encoded_chunks: list[str] = []
        stderr_chunks: list[str] = []
        deadline = time.monotonic() + 1800
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
        stderr = "".join(stderr_chunks)
        if stderr.strip():
            raise RuntimeError(f"download command wrote stderr: {stderr.strip()}")
        try:
            payload = base64.b64decode("".join(encoded_chunks), validate=True)
        except ValueError as error:
            raise RuntimeError(f"download of {name}:{src_path} returned invalid base64") from error
        fo = BytesIO(payload)
        with tarfile.open(fileobj=fo) as tar:
            try:
                tar.extractall(dst_path, filter="data")
            except TypeError:
                tar.extractall(dst_path)

    def peek(self, name: str, path: str) -> str:
        exec_command = ["cat", path]
        resp = stream(
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

        output = ""
        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                output += resp.read_stdout()
        resp.close()
        return output

    def get_pod_resource_usage(self, name: str) -> dict[str, float] | None:
        """
        Get memory usage of a pod by reading /proc/self/status.
        Returns dict with memory_mb and memory_limit_mb, or None if failed.
        """
        try:
            # Read process memory info from /proc
            exec_command = ["cat", "/proc/self/status"]
            resp = stream(
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

            output = ""
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

    def upload(self, name: str, src_path: str, dst_path: str) -> None:
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w:tar") as tar:
            tar.add(src_path, arcname=dst_path)
        payload = base64.b64encode(buf.getvalue()).decode("ascii")
        remote_payload = f"/tmp/coinjoin-emulator-upload-{uuid.uuid4().hex}.b64"
        deadline = time.monotonic() + UPLOAD_TIMEOUT_SECONDS

        def exec_checked(exec_command: list[str]) -> None:
            resp = stream(
                self.client.connect_get_namespaced_pod_exec,
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
                if time.monotonic() >= deadline:
                    resp.close()
                    raise TimeoutError(f"Timed out uploading {src_path} to {name}:{dst_path}")
                resp.update(timeout=1)
                if resp.peek_stdout():
                    resp.read_stdout()
                if resp.peek_stderr():
                    stderr_chunks.append(resp.read_stderr())
            returncode = getattr(resp, "returncode", None)
            resp.close()
            stderr = "".join(stderr_chunks).strip()
            if returncode not in (None, 0) or stderr:
                detail = f": {stderr}" if stderr else ""
                raise RuntimeError(f"upload to {name}:{dst_path} failed{detail}")

        try:
            for offset in range(0, len(payload), UPLOAD_COMMAND_CHUNK_SIZE):
                chunk = payload[offset : offset + UPLOAD_COMMAND_CHUNK_SIZE]
                redirect = ">" if offset == 0 else ">>"
                exec_checked(
                    ["sh", "-c", f'printf "%s" "$1" {redirect} "$2"', "sh", chunk, remote_payload]
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
        # without this, the cleaunup fails because of open websocket channel from log gathering
        # but when the fresh client is created, the log gathering fails...
        # "Working" config is letting the cleanup fail and restarting it after run...
        # fresh_client = client.CoreV1Api()
        # self.client = fresh_client
        # return

        try:
            pods = self.client.list_namespaced_pod(  # type: ignore[call-arg]
                namespace=self._namespace,
                label_selector=f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}",
            )
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
        services = self.client.list_namespaced_service(  # type: ignore[call-arg]
            namespace=self._namespace,
            label_selector=f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}",
        )
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
