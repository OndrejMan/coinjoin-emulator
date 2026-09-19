import json
from time import monotonic, sleep

import requests

WALLET_NAME = "wallet"


class WasabiBackend:
    def __init__(self, host="localhost", port=37127, internal_ip="", proxy=""):
        self.host = host
        self.port = port
        self.internal_ip = internal_ip
        self.proxy = proxy

    def _rpc(self, request):
        request["jsonrpc"] = "2.0"
        request["id"] = "1"
        try:
            response = requests.post(
                f"http://{self.host}:{self.port}/{WALLET_NAME}",
                data=json.dumps(request),
                proxies=dict(http=self.proxy),
                timeout=5,
            )
        except requests.exceptions.Timeout:
            return "timeout"
        if "error" in response.json():
            raise Exception(response.json()["error"])
        if "result" in response.json():
            return response.json()["result"]
        return None

    def _get_status(self):
        response = requests.get(
            f"http://{self.host}:{self.port}/api/v4/btc/Blockchain/status",
            proxies=dict(http=self.proxy),
            timeout=5,
        )
        return response.json()

    def wait_ready(self, timeout=120):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            try:
                self._get_status()
                return
            except Exception:
                pass
            sleep(0.1)
        raise TimeoutError(f"{self.__class__.__name__} at {self.host}:{self.port} was not ready after {timeout}s")
