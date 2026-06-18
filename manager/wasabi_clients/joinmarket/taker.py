# pylint: disable=assignment-from-no-return,unused-argument

from time import sleep, time
from typing import TYPE_CHECKING

import requests

from ...exceptions import RpcError
from .types import STOP_SERVICE_NOT_RUNNING_MESSAGE, JsonDict, is_stop_service_not_running_error


class JoinMarketTakerMixin:
    walletname: str
    role: str
    coinjoin_in_process: bool
    maker_running: bool

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

        def stop_maker(self) -> JsonDict | bool: ...

    def start_coinjoin(
        self,
        mixdepth: int,
        amount_sats: int,
        counterparties: int,
        destination: str,
        txfee: int | None = None,
    ) -> JsonDict:
        """
        Initiate a coinjoin as taker.
        - mixdepth: int, the mixdepth to spend from
        - amount_sats: int, amount in satoshis to coinjoin
        - counterparties: int, number of counterparties to coinjoin with
        - destination: str, address to send the coinjoined funds to
        - txfee: optional, int, Bitcoin miner fee to use for transaction
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/coinjoin"
        json_data: JsonDict = {
            "mixdepth": mixdepth,
            "amount_sats": amount_sats,
            "counterparties": counterparties,
            "destination": destination,
        }
        if txfee is not None:
            json_data["txfee"] = txfee
        response = self._rpc(method, endpoint, json_data=json_data)
        return response

    def run_schedule(
        self,
        destination_addresses: list[str],
        tumbler_options: JsonDict | None = None,
    ) -> JsonDict:
        """
        Create and run a schedule of transactions.
        - destination_addresses: list of str, addresses to send funds to
        - tumbler_options: optional, dict, additional tumbler configuration options
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        json_data: JsonDict = {
            "destination_addresses": destination_addresses,
        }
        if tumbler_options:
            json_data["tumbler_options"] = tumbler_options
        response = self._rpc(method, endpoint, json_data=json_data)
        return response

    def get_schedule(self) -> JsonDict:
        """Get the schedule that is currently running."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        response = self._rpc(method, endpoint)
        return response

    def stop_coinjoin(self) -> JsonDict | bool:
        """Stop a running coinjoin attempt."""
        if self.role == "taker" and self.coinjoin_in_process:
            response = self.stop_taker()
            self.coinjoin_in_process = False
            return response
        if self.role == "maker" and self.maker_running:
            response = self.stop_maker()
            self.maker_running = False
            return response
        print("No coinjoin in process")
        return True

    def stop_taker(self) -> JsonDict | bool:
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/stop"
        try:
            return self._rpc(method, endpoint)
        except RpcError as e:
            if is_stop_service_not_running_error(e):
                print(STOP_SERVICE_NOT_RUNNING_MESSAGE)
                return True
            raise

    def send(self, addressed_fundings: list[tuple[str, int]]) -> list[JsonDict]:
        results: list[JsonDict] = []
        try:
            for address, amount in addressed_fundings:
                result = self.simple_send(destination_address=address, amount_sats=amount)
                results.append(result)
                print(f"- sent {amount} sats to {address}")
                sleep(5)  # The btc node needs time to process the transaction
        except (requests.exceptions.RequestException, RpcError, TimeoutError, KeyError, TypeError, ValueError) as e:
            print(f"- error during fund distribution: {e}")
            raise
        return results

    def simple_send(
        self,
        destination_address: str,
        amount_sats: int,
        mixdepth: int = 0,
        txfee: int = 5000,
    ) -> JsonDict:
        """
        Send funds to a single address without coinjoin.
        - destination_address: str, address to send funds to
        - amount_sats: int, amount in satoshis to send
        - mixdepth: int, the mixdepth to spend from
        - txfee: int, miner fee in satoshis
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/direct-send"
        json_data: JsonDict = {
            "destination": destination_address,
            "amount_sats": amount_sats,
            "txfee": txfee,
            "mixdepth": mixdepth,
        }
        start = time()
        while time() - start < 30:
            try:
                response = self._rpc(method, endpoint, json_data=json_data)
                return response
            except (requests.exceptions.RequestException, RpcError, TimeoutError, KeyError, TypeError, ValueError) as e:
                print(e)
                sleep(2)

        raise TimeoutError("Failed to send funds, attempt timed out.")
