from collections.abc import Mapping, Sequence

class V1DeleteOptions: ...

class ObjectMeta:
    name: str

class PodStatus:
    pod_ip: str | None

class PodStatusResponse:
    status: PodStatus

class ServicePort:
    target_port: int
    node_port: int

class ServiceSpec:
    ports: Sequence[ServicePort]

class ServiceResponse:
    spec: ServiceSpec

class NamedResource:
    metadata: ObjectMeta

class ResourceList:
    items: Sequence[NamedResource]

class CoreV1Api:
    def create_namespace(self, *, body: Mapping[str, object]) -> object: ...
    def create_namespaced_pod(
        self, *, body: Mapping[str, object], namespace: str
    ) -> object: ...
    def read_namespaced_pod_status(
        self, *, name: str, namespace: str
    ) -> PodStatusResponse: ...
    def create_namespaced_service(
        self, *, body: Mapping[str, object], namespace: str
    ) -> ServiceResponse: ...
    def delete_namespaced_pod(self, *, name: str, namespace: str) -> object: ...
    def delete_namespaced_service(self, name: str, *, namespace: str) -> object: ...
    def connect_get_namespaced_pod_exec(self, *args: object, **kwargs: object) -> object: ...
    def read_namespaced_pod_log(self, *, name: str, namespace: str) -> str: ...
    def list_namespaced_pod(self, *, namespace: str) -> ResourceList: ...
    def list_namespaced_service(self, *, namespace: str) -> ResourceList: ...
    def delete_namespace(
        self, *, name: str, body: V1DeleteOptions
    ) -> object: ...
