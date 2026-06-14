from abc import ABC, abstractmethod
from collections.abc import Iterable
from multiprocessing.pool import ThreadPool


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
        env: dict[str, str | None] | None = None,
        ports: dict[int, int] | None = None,
        skip_ip: bool = False,
        cpu: float = 0.1,
        memory: int = 768,
        volumes: dict[str, dict[str, str]] | None = None,
    ) -> tuple[str, dict[int, int]]:
        pass

    @abstractmethod
    def stop(self, name: str) -> object:
        pass

    def stop_many(self, names: Iterable[str]) -> None:
        with ThreadPool() as p:
            p.map(lambda x: self.stop(x), names)

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
