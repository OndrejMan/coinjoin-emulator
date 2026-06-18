from typing import TYPE_CHECKING

import requests

from .types import JoinmarketConflictException, JsonDict


class JoinMarketMakerMixin:
    walletname: str

    if TYPE_CHECKING:
        def _rpc(
            self,
            method: str,
            endpoint: str,
            json_data: JsonDict | None = None,
            timeout: int = 5,
            repeat: int = 4,
            auth_required: bool = True,
        ) -> JsonDict: ...

    def get_yieldgen_report(self) -> JsonDict:
        """Get the latest report on yield-generating activity."""
        method = "GET"
        endpoint = "/wallet/yieldgen/report"
        response = self._rpc(method, endpoint)
        return response

    def start_maker(
        self,
        txfee: int | str,
        cjfee_a: int | str,
        cjfee_r: float | str,
        ordertype: str,
        minsize: int | str,
    ) -> JsonDict | requests.Response:
        """
        Start the yield generator service with the specified configuration.
        - txfee: str or int, e.g., "0" (absolute fee in satoshis)
        - cjfee_a: str or int, e.g., "5000" (absolute coinjoin fee in satoshis)
        - cjfee_r: str or float, e.g., "0.00004" (relative coinjoin fee as a fraction)
        - ordertype: str, e.g., "reloffer" or "absoffer"
        - minsize: str or int, minimum coinjoin size in satoshis. Should be higher then 27300sats
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/maker/start"
        json_data: JsonDict = {
            "txfee": str(txfee),
            "cjfee_a": str(cjfee_a),
            "cjfee_r": str(cjfee_r),
            "ordertype": ordertype,
            "minsize": str(minsize),
        }

        try:
            return self._rpc(method, endpoint, json_data=json_data)
        except JoinmarketConflictException as e:
            detail = getattr(e.response, "text", "") or str(e)
            print(f"Could not start maker: {detail}")
            return e.response

    def stop_maker(self) -> JsonDict:
        """Stop the yield generator service."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/maker/stop"
        # When stopping not running maker, returns 401 response
        response = self._rpc(method, endpoint)
        return response

    def list_transactions_maker(self) -> JsonDict:
        """List all transactions in the wallet."""
        method = "GET"
        endpoint = "/wallet/yieldgen/report"
        response = self._rpc(method, endpoint)
        return response
