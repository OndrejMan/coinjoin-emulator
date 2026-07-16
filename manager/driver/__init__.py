import tarfile
from abc import ABC, abstractmethod
from collections.abc import Iterable
from multiprocessing.pool import ThreadPool


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
