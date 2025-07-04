import base64
from functools import cached_property
from io import BytesIO
import os
import tarfile
from time import sleep
from . import Driver
from kubernetes import client, config
from kubernetes.stream import stream
from kubernetes.client.exceptions import ApiException
import backoff


class KubernetesDriver(Driver):
    def __init__(self, namespace="coinjoin", reuse_namespace=False, pull_secret_path=None):
        config.load_kube_config()
        self.client = client.CoreV1Api()
        self._namespace = namespace
        self.reuse_namespace = reuse_namespace
        self.pull_secret_path = pull_secret_path

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

    def build_pod_manifest(self, name, image, env, ports, cpu, memory,
                            user_id=None):
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
                            "limits": {"cpu": cpu, "memory": f"{memory}Mi"},
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
        name,
        image,
        env=None,
        ports=None,
        cpu=None,
        memory=None,
        run_as_user=None,
        **kwargs
    ):
        pod_manifest = self.build_pod_manifest(name, image, env, ports, cpu, memory, run_as_user)
        resp = self.client.create_namespaced_pod(body=pod_manifest, namespace=self.namespace)

        pod_ip = None
        while pod_ip is None:
            pod_ip = self.client.read_namespaced_pod_status(
                name=name, namespace=self.namespace
            ).status.pod_ip
            sleep(1)

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
        resp = self.client.create_namespaced_service(
            body=service_manifest, namespace=self.namespace
        )
        port_mapping = dict(
            map(lambda x: (x.target_port, x.node_port), resp.spec.ports)
        )
        return pod_ip or "", port_mapping, None

    def stop(self, name):
        try:
            self.client.delete_namespaced_pod(name=name, namespace=self.namespace)
            self.client.delete_namespaced_service(
                f"{name}-service", namespace=self.namespace
            )
        except:
            pass

    def download(self, name, src_path, dst_path):
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

        fo = BytesIO()
        while resp.is_open():
            resp.update(timeout=10)
            if resp.peek_stdout():
                fo.write(resp.read_stdout().encode())
        fo.seek(0)
        with tarfile.open(fileobj=fo) as tar:
            tar.extractall(dst_path)
        resp.close()

    def peek(self, name, path):
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

    def upload(self, name, src_path, dst_path):
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

    def cleanup(self, image_prefix=""):
        pods = self.client.list_namespaced_pod(namespace=self._namespace)
        for pod in pods.items:
            if any(
                    x in pod.metadata.name
                    for x in ("irc-server", "btc-node", "wasabi-backend", "wasabi-coordinator", "wasabi-client",
                              "joinmarket-client-server", "joinmarket-distributor", "jcs")
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
                    for x in ("irc-server", "btc-node", "wasabi-backend", "wasabi-coordinator", "wasabi-client",
                              "joinmarket-client-server", "joinmarket-distributor", "jcs")
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
