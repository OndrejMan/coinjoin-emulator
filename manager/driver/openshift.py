"""
OpenshiftDriver: Kubernetes driver extension for OpenShift compatibility.

- Injects serviceAccountName and securityContext (runAsUser, runAsGroup, runAsNonRoot)
  into pod/deployment securityContext.
- Avoids code duplication by inheriting from KubernetesDriver.
- Ensures containers work under OpenShift's restricted SCC (random UID, root group).
- All other logic is reused from KubernetesDriver.
"""
import subprocess
import time
from typing import cast

from kubernetes import client
from kubernetes.client.rest import ApiException

from .kubernetes import KubernetesDriver


class OpenshiftDriver(KubernetesDriver):
    def __init__(
        self,
        namespace: str = "coinjoin",
        reuse_namespace: bool = False,
        pull_secret_path: str | None = None,
    ) -> None:
        super().__init__(namespace, reuse_namespace, pull_secret_path)

    def ensure_service_account(self, service_account: str) -> None:
        # Create the service account if it does not exist
        v1 = self.client
        sa_manifest = client.V1ServiceAccount(metadata=client.V1ObjectMeta(name=service_account))
        try:
            v1.create_namespaced_service_account(namespace=self.namespace, body=sa_manifest)
            print(f"Created service account '{service_account}' in namespace '{self.namespace}'")
        except ApiException as e:
            if e.status != 409:
                print(f"Failed to create service account '{service_account}': {e}")
                raise
        # Attempt to grant anyuid SCC automatically
        try:
            result = subprocess.run([
                "oc", "adm", "policy", "add-scc-to-user", "anyuid",
                "-z", service_account, "-n", self.namespace
            ], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                print(
                    f"[INFO] Granted 'anyuid' SCC to service account '{service_account}' "
                    f"in namespace '{self.namespace}'."
                )
            else:
                print(f"[WARNING] Could not grant 'anyuid' SCC to '{service_account}': {result.stderr.strip()}")
        except Exception as e:
            print(f"[WARNING] Failed to run 'oc adm policy add-scc-to-user': {e}")

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
        group_id: int | None = None,
        service_account: str = "jm",
        run_as_user: int = 1000,
        run_as_group: int = 1000,
    ) -> dict[str, object]:
        manifest = super().build_pod_manifest(
            name, image, env, ports, cpu, memory, user_id, volumes, command, group_id=group_id
        )
        # Inject ServiceAccount and securityContext
        spec = cast(dict[str, object], manifest["spec"])
        spec["serviceAccountName"] = service_account
        spec["securityContext"] = {
            "runAsUser": run_as_user,
            "runAsGroup": run_as_group,
            "runAsNonRoot": True
        }
        return manifest

    def run(
        self,
        name: str,
        image: str,
        env: dict[str, str] | None = None,
        ports: dict[int, int] | None = None,
        cpu: float | None = 0.1,
        memory: int | None = 768,
        **kwargs: object,
    ) -> tuple[str, dict[int, int], object]:
        """
        Override pod creation to inject OpenShift-compatible securityContext.
        These parameters are per-run, allowing different containers to use different accounts/UIDs.
        """
        service_account = str(kwargs.get("service_account", "jm"))
        # Callers may pass these through as None when they have no opinion.
        run_as_user = int(cast(int, kwargs.get("run_as_user") or 1000))
        run_as_group = int(cast(int, kwargs.get("run_as_group") or run_as_user))
        skip_ip = bool(kwargs.get("skip_ip", False))
        volumes = cast(dict[str, dict[str, str]] | None, kwargs.get("volumes"))
        command = cast(list[str] | None, kwargs.get("command"))

        self.ensure_service_account(service_account)
        # Call the parent's pod manifest creation logic
        pod_manifest = self.build_pod_manifest(
            name,
            image,
            env,
            ports,
            cpu,
            memory,
            user_id=None,
            volumes=volumes,
            command=command,
            service_account=service_account,
            run_as_user=run_as_user,
            run_as_group=run_as_group,
        )
        return self._create_and_wait_for_pod(pod_manifest, name, skip_ip)

    def _create_and_wait_for_pod(
        self, pod_manifest: dict[str, object], name: str, skip_ip: bool
    ) -> tuple[str, dict[int, int], object]:
        # Use parent's client to create and wait for pod
        resp = self.client.create_namespaced_pod(
            namespace=self.namespace,
            body=pod_manifest
        )
        if skip_ip:
            return "", {}, None
        # Wait for pod to be running and get IP
        for _ in range(60):
            pod = self.client.read_namespaced_pod_status(
                name=name, namespace=self.namespace
            )
            if pod.status.phase == "Running" and pod.status.pod_ip:
                pod_ip = pod.status.pod_ip
                break
            time.sleep(1)
        else:
            raise TimeoutError(f"Pod {name} did not become ready in time.")

        # Using the same name as the pod
        service_name = name
        spec = cast(dict[str, object], pod_manifest["spec"])
        containers = cast(list[dict[str, object]], spec.get("containers", [{}]))
        container_ports = cast(list[dict[str, int]], containers[0].get("ports", []))
        port_dict = {p["containerPort"]: p["containerPort"] for p in container_ports if "containerPort" in p}
        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": service_name},
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
                    for (target_port, container_port) in port_dict.items()
                ],
            },
        }

        print(f"Creating service '{service_name}' in namespace '{self.namespace}'")

        resp = self.client.create_namespaced_service(
            body=service_manifest, namespace=self.namespace
        )
        port_mapping = dict(
            map(lambda x: (x.target_port, x.node_port), resp.spec.ports)
        )
        print(f"Port mapping for service '{service_name}': {port_mapping}")

        # Create an OpenShift Route for this service
        route_host = None
        try:
            route_name = service_name
            # Use oc to create a route (exposing the first port)
            target_port = list(port_dict.keys())[0] if port_dict else 80
            cmd = [
                "oc", "create", "route", "passthrough", route_name,
                f"--service={service_name}",
                f"--port={target_port}",
                "-n", self.namespace,
                "--insecure-policy=Redirect"
            ]
            print(f"Creating route for service '{service_name}': {' '.join(cmd)}")
            subprocess.run(cmd, check=True, capture_output=True)
            # Get the route host
            get_cmd = [
                "oc", "get", "route", route_name, "-n", self.namespace, "-o", "jsonpath={.spec.host}"
            ]
            route_host = subprocess.check_output(get_cmd).decode().strip()
            print(f"Route created for service '{service_name}': {route_host}")
        except Exception as e:
            print(f"[WARNING] Could not create route for service '{service_name}': {e}")
        return pod_ip, port_mapping, route_host
