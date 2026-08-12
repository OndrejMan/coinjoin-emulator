"""Maker (yield generator) control calls."""

from typing import TYPE_CHECKING

from .types import JoinmarketConflictException, JsonDict


class JoinMarketMakerMixin:
    """Starts and stops the yield generator and reads its offers."""

    walletname: str
    maker_running: bool
    offers: list[JsonDict]

    if TYPE_CHECKING:
        def _rpc(
            self,
            method: str,
            endpoint: str,
            json_data: JsonDict | None = None,
            timeout: int = 60,
            repeat: int = 4,
        ) -> JsonDict: ...

        async def _rpc_async(
            self,
            method: str,
            endpoint: str,
            json_data: JsonDict | None = None,
            timeout: int = 60,
            repeat: int = 4,
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
        maxsize: int | str,
    ) -> object:
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
            "maxsize": str(maxsize)
        }

        try:
            return self._rpc(method, endpoint, json_data=json_data)
        except JoinmarketConflictException as e:
            print("Could not start maker without confirmed balance")
            return e.response

    async def start_maker_async(
        self,
        txfee: int | str,
        cjfee_a: int | str,
        cjfee_r: float | str,
        ordertype: str,
        minsize: int | str,
        maxsize: int | str,
    ) -> object:
        """
        Async start the yield generator service with the specified configuration.
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
            "maxsize": str(maxsize)
        }

        try:
            return await self._rpc_async(method, endpoint, json_data=json_data)
        except JoinmarketConflictException as e:
            print("Could not start maker without confirmed balance")
            return e.response

    def stop_maker(self) -> JsonDict:
        """Stop the yield generator service."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/maker/stop"
        # When stopping not running maker, returns 401 response
        response = self._rpc(method, endpoint)
        return response

    async def stop_maker_async(self) -> JsonDict:
        """Async stop the yield generator service."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/maker/stop"
        # When stopping not running maker, returns 401 response
        response = await self._rpc_async(method, endpoint)
        return response

    def list_transactions_maker(self) -> JsonDict:
        """List all transactions in the wallet."""
        method = "GET"
        endpoint = "/wallet/yieldgen/report"
        response = self._rpc(method, endpoint)
        return response

    def get_offer(self, round: int = 0) -> dict[str, object]:
        return self.offers[round % len(self.offers)]
