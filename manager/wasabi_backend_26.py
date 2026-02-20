import json
from traceback import print_exception
import requests
from time import sleep

WALLET_NAME = "wallet"


class WasabiBackend26:
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
        # just to see whether the container is ready
        response = requests.get(
            f"http://{self.host}:{self.port}/api/software/versions",
            proxies=dict(http=self.proxy),
            timeout=5,
        )
        return response.json()

    def wait_ready(self):
        while True:
            try:
                self._get_status()
                break
            except Exception as e:
                pass
            sleep(1)
