# pylint: disable=unused-argument,redefined-builtin
from collections.abc import Iterable
from io import BytesIO

class ImageNotFound(Exception): ...
class NotFound(Exception): ...

class APIError(Exception):
    explanation: str | None
    def __init__(
        self,
        message: str = ...,
        response: object | None = ...,
        explanation: str | None = ...,
    ) -> None: ...

class _Errors:
    ImageNotFound: type[ImageNotFound]
    NotFound: type[NotFound]
    APIError: type[APIError]

errors: _Errors

class ImageCollection:
    def get(self, name: str) -> object: ...
    def build(self, *, path: str, tag: str, rm: bool, nocache: bool) -> object: ...
    def pull(self, name: str) -> object: ...

class Container:
    name: object
    attrs: dict[str, dict[str, str]]
    def stop(self) -> None: ...
    def remove(self, *, force: bool) -> None: ...
    def get_archive(self, path: str) -> tuple[Iterable[bytes], object]: ...
    def put_archive(self, path: str, data: BytesIO) -> object: ...
    def logs(self, *, stdout: bool, stderr: bool) -> bytes: ...

class ContainerCollection:
    def get(self, name: str) -> Container: ...
    def run(
        self,
        image: str,
        *,
        detach: bool,
        auto_remove: bool,
        name: str,
        hostname: str,
        network: str,
        ports: dict[str, int],
        environment: dict[str, str],
        volumes: dict[str, dict[str, str]] | None,
        command: list[str] | None,
    ) -> object: ...
    def list(self, *, all: bool = ...) -> list[Container]: ...

class Network:
    id: str
    def remove(self) -> None: ...

class NetworkCollection:
    def create(self, name: str, *, driver: str) -> Network: ...
    def list(self, name: str) -> list[Network]: ...

class DockerClient:
    images: ImageCollection
    containers: ContainerCollection
    networks: NetworkCollection

def from_env() -> DockerClient: ...
