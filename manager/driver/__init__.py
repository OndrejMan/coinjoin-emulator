import tarfile
from abc import ABC, abstractmethod
from collections.abc import Iterable
from multiprocessing.pool import ThreadPool

# Wasabi pins its service ports (backend 37127, coordinator and client RPC 37128,
# host-side mappings up to 37260) inside the default Linux ephemeral port range
# (net.ipv4.ip_local_port_range is 32768-60999). Any outbound connection opened in
# the same network namespace before the server binds can be handed one of those
# ports as its source port, and the listener then dies with
# "Failed to bind to address http://0.0.0.0:37128: address already in use" - the
# coordinator hits this because it talks to the bitcoin RPC in its startup task
# before Kestrel binds. Reserving the block keeps the kernel from assigning these
# ports to outbound sockets; the servers can always bind them.
RESERVED_PORT_RANGE = "37127-37260"
RESERVED_PORTS_SYSCTL = "net.ipv4.ip_local_reserved_ports"


def extract_tar(tar: tarfile.TarFile, dst_path: str) -> None:
    """Extract an archive received from a container, sanitizing member paths."""
    try:
        tar.extractall(dst_path, filter="data")
    except TypeError:
        # Python without the extraction-filter parameter (< 3.10.12/3.11.4)
        tar.extractall(dst_path)  # noqa: S202  # nosec - trusted emulator containers


class Driver(ABC):
    # True when the manager reaches services at their container/pod address
    # directly (no port-forwarding or host port mapping involved).
    direct_network: bool = False

    @abstractmethod
    def has_image(self, name: str) -> bool:
        pass

    @abstractmethod
    def build(self, name: str, path: str) -> object:
        pass

    @abstractmethod
    def pull(self, name: str) -> object:
        pass

    @abstractmethod
    def run(
        self,
        name: str,
        image: str,
        env: dict[str, str | None] | None = None,
        ports: dict[int, int] | None = None,
        skip_ip: bool = False,
        cpu: float = 0.1,
        memory: int = 768,
        cpu_request: float | None = None,
        memory_request: int | None = None,
        volumes: dict[str, dict[str, str]] | None = None,
        command: list[str] | None = None,
    ) -> tuple[str, dict[int, int]]:
        pass

    @abstractmethod
    def stop(self, name: str) -> object:
        pass

    def stop_many(self, names: Iterable[str]) -> None:
        with ThreadPool() as p:
            p.map(self.stop, names)

    @abstractmethod
    def download(self, name: str, src_path: str, dst_path: str) -> object:
        pass

    @abstractmethod
    def peek(self, name: str, path: str, *, missing_ok: bool = False) -> str:
        pass

    @abstractmethod
    def logs(self, name: str) -> str:
        pass

    @abstractmethod
    def upload(self, name: str, src_path: str, dst_path: str) -> object:
        pass

    @abstractmethod
    def cleanup(self, image_prefix: str = "") -> object:
        pass

    def diagnostics(self) -> str:
        """Return runtime diagnostics before cleanup removes managed resources."""
        return ""
