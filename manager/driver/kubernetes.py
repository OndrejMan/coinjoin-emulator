import os
import tarfile
from functools import cached_property
from io import BytesIO
from time import sleep

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream

from manager import log_output as log

from . import Driver


class KubernetesDriver(Driver):
    def __init__(self, namespace: str = "coinjoin", reuse_namespace: bool = False) -> None:
        config.load_kube_config()
        self.client = client.CoreV1Api()
        self._namespace = namespace
        self.reuse_namespace = reuse_namespace

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
        port_mapping = dict(
            map(lambda x: (x.target_port, x.node_port), resp.spec.ports)
        )
        return pod_ip or "", port_mapping

    def stop(self, name: str) -> None:
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
