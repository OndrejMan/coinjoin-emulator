from abc import ABC, abstractmethod
from collections.abc import Iterable
from multiprocessing.pool import ThreadPool

RESERVED_PORT_RANGE = "37127-37260"
RESERVED_PORTS_SYSCTL = "net.ipv4.ip_local_reserved_ports"


class Driver(ABC):
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
        env: dict[str, str] | None = None,
        ports: dict[int, int] | None = None,
        cpu: float | None = None,
        memory: int | None = None,
        **kwargs: object,
    ) -> tuple[str, dict[int, int], object]:
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
    def peek(self, name: str, path: str) -> str:
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
