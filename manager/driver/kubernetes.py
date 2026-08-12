import base64
import glob
import os
import tarfile
import time
import traceback
from functools import cached_property
from io import BytesIO
from time import sleep
from typing import cast

import backoff
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream

from manager.exceptions import CoinjoinEmulatorError

from . import Driver

DEFAULT_CPU = 0.1
DEFAULT_MEMORY = 768


class KubernetesDriver(Driver):
    def __init__(
        self,
        namespace: str = "coinjoin",
        reuse_namespace: bool = False,
        pull_secret_path: str | None = None,
        in_cluster: bool = False,
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
    ) -> dict[str, object]:
        if cpu is None:
            cpu = DEFAULT_CPU
        if memory is None:
            memory = DEFAULT_MEMORY
        if ports is None:
            ports = {}
        if env is None:
            env = {}

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

        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "labels": {"app": name}},
            "spec": {
                "restartPolicy": "Never",
                "containers": [
                    {
                        "image": image,
                        "imagePullPolicy": "Always",
                        "name": name,
                        "ports": [
                            {"containerPort": container_port}
                            for container_port in ports.keys()
                        ],
                        "env": [
                            {"name": k, "value": v}
                            for k, v in env.items()
                        ],
                        "securityContext": security_context,
                        "resources": {
                            "limits": {"cpu": cpu*1.5, "memory": f"{memory*1.5}Mi"},
                            "requests": {"cpu": cpu, "memory": f"{memory}Mi"},
                        },
                    }
                ],
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
        ports = ports or {}
        pod_manifest = self.build_pod_manifest(name, image, env, ports, cpu, memory, run_as_user)
        resp = self.client.create_namespaced_pod(body=pod_manifest, namespace=self.namespace)

        pod_ip = None
        try:
            while pod_ip is None:
                pod_ip = self.client.read_namespaced_pod_status(
                    name=name, namespace=self.namespace
                ).status.pod_ip
                sleep(1)
        except Exception as e:
            print(f"Failed to get pod IP: {e}")
            raise

        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": f"{name}"},
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
        # Use rsync-like approach with tar to handle files being written to
        # The --warning=no-file-changed flag helps handle files that change during reading
        # The --ignore-failed-read flag ensures the process continues even if some files can't be read
        exec_command = [
            "tar", "cf", "-",
            "--warning=no-file-changed",
            "--ignore-failed-read",
            "-C", src_parent, src_target
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
        print("Opening connection")

        fo = BytesIO()
        while resp.is_open():
            print("Updating stream")
            resp.update(timeout=10)
            if resp.peek_stdout():
                fo.write(resp.read_stdout().encode())
        print("")
        fo.seek(0)
        print("Closing connection")
        resp.close()

        with tarfile.open(fileobj=fo) as tar:
            print("Extracting")
            tar.extractall(dst_path)

        # Wait for required files to appear in dst_path
        start_time = time.time()
        timeout = 120  # 2 minutes
        found = False
        waited = False
        while True:
            tumble_log = os.path.exists(os.path.join(dst_path, "logs/TUMBLE.log"))
            tumble_schedule = bool(glob.glob(os.path.join(dst_path, "logs/TUMBLE.schedule*")))
            j_logs = glob.glob(os.path.join(dst_path, "logs/J*.log"))
            yifen = os.path.exists(os.path.join(dst_path, "logs/yigen-statement.csv"))

            cond1 = tumble_log and tumble_schedule and len(j_logs) > 0
            cond2 = len(j_logs) > 0 and yifen

            print(f"Debug: tumble_log={tumble_log}, tumble_schedule={tumble_schedule}, j_logs={j_logs}, yigen={yifen}")

            if cond1 or cond2:
                print(f"All required log files found in {dst_path} after {time.time() - start_time} seconds")
                print("Waiting for file transfer to complete...")
                time.sleep(10)
                if found:
                    print(
                        f"All required log files still found in {dst_path} "
                        f"after {time.time() - start_time} seconds"
                    )
                    time.sleep(1)
                    break
                found = True

            if time.time() - start_time > timeout:
                print(f"Timeout waiting for required log files in {dst_path}")
                break

            if not waited:
                print(f"Waiting for required log files to appear in {dst_path}...")
                waited = True
            time.sleep(2)

        # sleep(60)

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
        commands = [buf.getvalue()]

        exec_command = ["tar", "xf", "-", "-C", "/"]
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

        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                print(f"STDOUT: {resp.read_stdout()}")
            if resp.peek_stderr():
                print(f"STDERR: {resp.read_stderr()}")
            if commands:
                c = commands.pop(0)
                resp.write_stdin(c)
            else:
                break
        resp.close()


    def cleanup(self, image_prefix: str = "") -> None:
        # without this, the cleaunup fails because of open websocket channel from log gathering
        # but when the fresh client is created, the log gathering fails...
        # "Working" config is letting the cleanup fail and restarting it after run...
        # fresh_client = client.CoreV1Api()
        # self.client = fresh_client
        # return

        try:
            pods = self.client.list_namespaced_pod(namespace=self._namespace)
        except ApiException as e:
            print("Error listing pods:", e)
            traceback.print_exc()
            print("Cleanup failed")
            return

        for pod in pods.items:
            if any(
                    x in pod.metadata.name
                    for x in ("irc-server", "btc-node", "wasabi-backend", "wasabi-coordinator", "wasabi-client",
                              "joinmarket-client-server", "joinmarket-distributor", "jcs", "joinmarket-obwatch")
            ):
                try:
                    print(f"Deleting pod {pod.metadata.name}")
                    self.client.delete_namespaced_pod(
                        name=pod.metadata.name, namespace=self._namespace
                    )
                    print(f"Deleted pod {pod.metadata.name}")
                except ApiException:
                    pass
        services = self.client.list_namespaced_service(namespace=self._namespace)
        for service in services.items:
            if any(
                    x in service.metadata.name
                    for x in ("irc-server", "btc-node", "wasabi-backend", "wasabi-coordinator", "wasabi-client",
                              "joinmarket-client-server", "joinmarket-distributor", "jcs", "joinmarket-obwatch")
            ):
                try:
                    print("Deleting service", service.metadata.name)
                    self.client.delete_namespaced_service(
                        name=service.metadata.name, namespace=self._namespace
                    )
                    print("Deleted service", service.metadata.name)
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
