from traceback import print_exception
import requests
from time import sleep
from typing import cast


class WasabiCoordinator:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 37128,
        internal_ip: str = "",
        proxy: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.internal_ip = internal_ip
        self.proxy = proxy

    def _get_status(self) -> dict[str, object] | None:
        """Get coordinator status"""
        try:
            response = requests.get(
                f"http://{self.host}:{self.port}/wabisabi/human-monitor",
                proxies={"http": self.proxy},
                timeout=5,
            )
            return cast(dict[str, object], response.json())
        except (requests.exceptions.RequestException, ValueError):
            return None

    def get_status(self) -> dict[str, object] | None:
        """Get coordinator status."""
        return self._get_status()

    def _get_rounds(self) -> dict[str, object] | None:
        """Get active coinjoin rounds"""
        try:
            print(self.host, self.port, self.proxy)
            response = requests.get(
                f"http://{self.host}:{self.port}/wabisabi/human-monitor",
                proxies={"http": self.proxy},
                timeout=5,
            )
            return cast(dict[str, object], response.json())
        except (requests.exceptions.RequestException, ValueError) as e:
            print_exception(e)
            return None

    def wait_ready(self) -> None:
        """Wait for coordinator to be ready"""
        print("Waiting for coordinator to be ready...")
        while True:
            try:
                status = self._get_status()
                if status:
                    print(f"Coordinator ready: {status}")
                    break
            except (requests.exceptions.RequestException, ValueError):
                pass
            sleep(0.1)
