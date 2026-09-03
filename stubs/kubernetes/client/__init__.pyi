# pylint: disable=unused-argument
from collections.abc import Mapping, Sequence

class V1DeleteOptions: ...

class ObjectMeta:
    name: str

class PodStatus:
    phase: str | None
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
    def read_namespace(self, name: str) -> V1Namespace: ...
    def read_namespaced_pod(self, name: str, namespace: str) -> V1PodRead: ...
    def create_namespaced_secret(self, namespace: str, body: object) -> object: ...
    def create_namespaced_service_account(self, namespace: str, body: object) -> object: ...
    def replace_namespaced_secret(self, name: str, namespace: str, body: object) -> object: ...
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
    def connect_get_namespaced_pod_exec(self, *_args: object, **_kwargs: object) -> object: ...
    def connect_get_namespaced_pod_portforward(self, *_args: object, **_kwargs: object) -> object: ...
    def read_namespaced_pod_log(self, *, name: str, namespace: str) -> str: ...
    def list_namespaced_pod(self, *, namespace: str) -> ResourceList: ...
    def list_namespaced_service(self, *, namespace: str) -> ResourceList: ...
    def delete_namespace(
        self, *, name: str, body: V1DeleteOptions
    ) -> object: ...

class V1NamespaceStatus:
    phase: str

class V1Namespace:
    status: V1NamespaceStatus

class V1ResourceRequirements:
    limits: dict[str, str]

class V1Container:
    resources: V1ResourceRequirements

class V1PodSpec:
    node_name: str | None
    containers: list[V1Container]

class V1PodRead:
    spec: V1PodSpec
    status: object

class V1ObjectMeta:
    def __init__(self, *, name: str = ..., namespace: str = ..., labels: dict[str, str] = ...) -> None: ...

class V1ServiceAccount:
    def __init__(self, *, metadata: V1ObjectMeta = ...) -> None: ...

class V1Secret:
    def __init__(
        self,
        *,
        metadata: V1ObjectMeta = ...,
        type: str = ...,
        data: dict[str, str] = ...,
    ) -> None: ...
