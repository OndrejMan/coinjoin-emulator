# pylint: disable=unused-argument

import json
from typing import TYPE_CHECKING, cast

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from ...exceptions import RpcError
from .types import JoinmarketConflictException, JsonDict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class JoinMarketRpcMixin:
    host: str
    port: int
    proxy: str
    token: str
    refresh_token: str

    if TYPE_CHECKING:
        def unlock_wallet(self, password: str | None = None) -> JsonDict: ...

    def _headers(self, auth_required: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {}
        if auth_required and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _store_tokens(self, response: JsonDict) -> None:
        self.token = str(response.get("token", ""))
        self.refresh_token = str(response.get("refresh_token", ""))

    def _ensure_auth(self) -> None:
        if not self.token:
            self.unlock_wallet()
        if not self.token:
            raise RpcError("Could not authenticate JoinMarket wallet")

    def _handle_response_error(self, response: requests.Response) -> None:
        if response.status_code == 409:
            raise JoinmarketConflictException(f"Error {response.status_code}: {response.text}", response)
        try:
            print(response.json())
            error_message = response.json().get("message", "Unknown error")
        except json.JSONDecodeError:
            error_message = response.text
        raise RpcError(f"Error {response.status_code}: {error_message}")

    def _request_once(
        self,
        method: str,
        endpoint: str,
        json_data: JsonDict | None,
        timeout: int,
        auth_required: bool,
    ) -> requests.Response:
        return requests.request(
            method=method,
            url=f"https://{self.host}:{self.port}/api/v1{endpoint}",
            json=json_data or {},
            headers=self._headers(auth_required=auth_required),
            proxies={"http": self.proxy},
            timeout=timeout,
            verify=False,
        )

    def _response_json(self, response: requests.Response) -> JsonDict:
        return cast(JsonDict, response.json())

    def _rpc(
        self,
        method: str,
        endpoint: str,
        json_data: JsonDict | None = None,
        timeout: int = 5,
        repeat: int = 4,
        auth_required: bool = True,
    ) -> JsonDict:
        if auth_required:
            self._ensure_auth()

        response = None
        refreshed_after_401 = False
        for attempt in range(repeat):
            try:
                response = self._request_once(
                    method=method,
                    endpoint=endpoint,
                    json_data=json_data,
                    timeout=timeout,
                    auth_required=auth_required,
                )
            except requests.exceptions.Timeout:
                continue
            except InsecureRequestWarning:
                continue

            if response.status_code == 401:
                if not auth_required or refreshed_after_401 or attempt == repeat - 1:
                    break
                self.token = ""
                self.refresh_token = ""
                self.unlock_wallet()
                if not self.token:
                    raise RpcError("Could not authenticate JoinMarket wallet")
                refreshed_after_401 = True
                continue

            if response.status_code == 409:
                raise JoinmarketConflictException(f"Error {response.status_code}: {response.text}", response)

            if response.status_code >= 400:
                self._handle_response_error(response)

            return self._response_json(response)

        if response is not None:
            if response.status_code >= 400:
                self._handle_response_error(response)
            return self._response_json(response)

        raise TimeoutError("timeout")
