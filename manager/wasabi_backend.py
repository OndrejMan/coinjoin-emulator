import json
import requests
from time import sleep
from typing import cast

WALLET_NAME = "wallet"


class WasabiBackend:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 37127,
        internal_ip: str = "",
        proxy: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.internal_ip = internal_ip
        self.proxy = proxy

    def _rpc(self, request: dict[str, object]) -> object:
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

    def _get_status(self) -> dict[str, object]:
        response = requests.get(
            f"http://{self.host}:{self.port}/api/v4/btc/Blockchain/status",
            proxies=dict(http=self.proxy),
            timeout=5,
        )
        return cast(dict[str, object], response.json())

    def wait_ready(self) -> None:
        while True:
            try:
                self._get_status()
                break
            except:
                pass
            sleep(0.1)
