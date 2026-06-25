import os
import select
import socket
import tarfile
import threading
from functools import cached_property
from io import BytesIO
from time import sleep
from typing import Protocol

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import portforward, stream

from manager import log_output as log

from . import Driver


class SocketLike(Protocol):
    def recv(self, size: int) -> bytes: ...
    def sendall(self, data: bytes) -> None: ...
    def fileno(self) -> int: ...


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
            forward = portforward(
                self.kube_client.connect_get_namespaced_pod_portforward,
                self.pod_name,
                self.namespace,
                ports=str(self.remote_port),
            )
            upstream_socket = forward.socket(self.remote_port)
            self.bridge(client_socket, upstream_socket)
        except Exception as error:  # pragma: no cover - defensive logging around background thread
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
    def __init__(self, namespace: str = "coinjoin", reuse_namespace: bool = False) -> None:
        config.load_kube_config()
        self.client = client.CoreV1Api()
        self._namespace = namespace
        self.reuse_namespace = reuse_namespace
        self.control_host = "127.0.0.1"
        self.port_forwards: dict[tuple[str, int], PortForwardServer] = {}

    @cached_property
    def namespace(self) -> str:
        namespace_manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": self._namespace},
        }
        if not self.reuse_namespace:
            self.client.create_namespace(body=namespace_manifest)
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
        volumes: dict[str, dict[str, str]] | None = None,
        command: list[str] | None = None,
    ) -> tuple[str, dict[int, int]]:
        if ports is None:
            ports = {}
        if env is None:
            env = {}
        volume_mounts = []
        pod_volumes = []
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

        container_spec = {
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
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "capabilities": {
                    "drop": ["ALL"],
                },
                "runAsNonRoot": True,
                "seccompProfile": {
                    "type": "RuntimeDefault",
                },
            },
            "resources": {
                "limits": {
                    "cpu": cpu,
                    "memory": f"{memory}Mi",
                },
                "requests": {
                    "cpu": cpu,
                    "memory": f"{memory}Mi",
                },
            },
        }
        if command is not None:
            container_spec["command"] = command

        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "labels": {"app": name}},
            "spec": {
                "restartPolicy": "Never",
                "containers": [container_spec],
                "volumes": pod_volumes,
            },
        }

        resp = self.client.create_namespaced_pod(
            body=pod_manifest, namespace=self.namespace
        )

        pod_ip = None
        if not skip_ip:
            while pod_ip is None:
                pod_ip = self.client.read_namespaced_pod_status(
                    name=name, namespace=self.namespace
                ).status.pod_ip
                sleep(1)

        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": f"{name}-service"},
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

        resp = self.client.create_namespaced_service(
            body=service_manifest, namespace=self.namespace
        )
        port_mapping = self.start_port_forwards(
            name,
            [int(port.target_port) for port in resp.spec.ports],
        )
        return pod_ip or "", port_mapping

    def start_port_forwards(self, name: str, ports: list[int]) -> dict[int, int]:
        port_mapping = {}
        for remote_port in ports:
            forward = PortForwardServer(self.client, self.namespace, name, remote_port)
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
        try:
            self.client.delete_namespaced_pod(name=name, namespace=self.namespace)
            self.client.delete_namespaced_service(
                f"{name}-service", namespace=self.namespace
            )
        except ApiException:
            pass

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        if src_path[-1] == "/":
            src_path = src_path[:-1]
        src_parent, src_target = os.path.split(src_path)
        exec_command = ["tar", "cf", "-", "-C", src_parent, src_target]
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

        fo = BytesIO()
        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                fo.write(resp.read_stdout().encode())
        fo.seek(0)
        with tarfile.open(fileobj=fo) as tar:
            tar.extractall(dst_path)
        resp.close()

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

    def logs(self, name: str) -> str:
        return self.client.read_namespaced_pod_log(name=name, namespace=self.namespace)

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
                log.debug(f"STDOUT: {resp.read_stdout()}")
            if resp.peek_stderr():
                log.error(f"STDERR: {resp.read_stderr()}")
            if commands:
                c = commands.pop(0)
                resp.write_stdin(c)
            else:
                break
        resp.close()

    def cleanup(self, image_prefix: str = "") -> None:
        self.close_port_forwards()
        pods = self.client.list_namespaced_pod(namespace=self._namespace)
        for pod in pods.items:
            if any(
                x in pod.metadata.name
                for x in (
                    "irc-server",
                    "btc-node",
                    "wasabi-backend",
                    "wasabi-coordinator",
                    "wasabi-client",
                    "joinmarket-client-server",
                )
            ):
                try:
                    self.client.delete_namespaced_pod(
                        name=pod.metadata.name, namespace=self._namespace
                    )
                except ApiException:
                    pass
        services = self.client.list_namespaced_service(namespace=self._namespace)
        for service in services.items:
            if any(
                x in service.metadata.name
                for x in (
                    "irc-server",
                    "btc-node",
                    "wasabi-backend",
                    "wasabi-coordinator",
                    "wasabi-client",
                    "joinmarket-client-server",
                )
            ):
                try:
                    self.client.delete_namespaced_service(
                        name=service.metadata.name, namespace=self._namespace
                    )
                except ApiException:
                    pass

        if not self.reuse_namespace:
            self.client.delete_namespace(
                name=self._namespace, body=client.V1DeleteOptions()
            )
