from traceback import print_exception
import requests
from time import monotonic, sleep


class WasabiCoordinator:
    def __init__(self, host="localhost", port=37128, internal_ip="", proxy=""):
        self.host = host
        self.port = port
        self.internal_ip = internal_ip
        self.proxy = proxy

    def _get_status(self):
        """Get coordinator status"""
        try:
            response = requests.get(
                f"http://{self.host}:{self.port}/wabisabi/human-monitor",
                proxies=dict(http=self.proxy),
                timeout=5,
            )
            return response.json()
        except Exception:
            return None

    def _get_rounds(self):
        """Get active coinjoin rounds"""
        try:
            print(self.host, self.port, self.proxy)
            response = requests.get(
                f"http://{self.host}:{self.port}/wabisabi/human-monitor",
                proxies=dict(http=self.proxy),
                timeout=5,
            )
            return response.json()
        except Exception as e:
            print_exception(e)
            return None

    def wait_ready(self, timeout=120):
        """Wait for coordinator to be ready, giving up after timeout seconds."""
        print("Waiting for coordinator to be ready...")
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            try:
                status = self._get_status()
                if status:
                    print(f"Coordinator ready: {status}")
                    return
            except Exception:
                pass
            sleep(0.1)
        raise TimeoutError(
            f"Wasabi coordinator at {self.host}:{self.port} was not ready after {timeout}s"
        )
