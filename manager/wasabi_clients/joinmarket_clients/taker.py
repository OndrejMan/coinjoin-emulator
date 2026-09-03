"""Taker and tumbler calls: coinjoins, schedules and direct sends."""

# The sibling methods are declared under TYPE_CHECKING, so pylint cannot see
# that they return a value.
# pylint: disable=assignment-from-no-return

import asyncio
from time import sleep, time
from typing import TYPE_CHECKING, cast

from manager.exceptions import CoinjoinEmulatorError

from .types import JsonDict


class JoinMarketTakerMixin:
    """Starts coinjoins, runs tumbler schedules and sends funds directly."""

    name: str
    walletname: str
    type: str
    coinjoin_in_process: bool
    maker_running: bool
    tumbler_options: JsonDict | None
    round_events: list[JsonDict]

    if TYPE_CHECKING:
        # pylint: disable=unused-argument  # these are stub signatures
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

        def get_new_address(self, mixdepth: int = 0) -> str: ...
        def stop_maker(self) -> JsonDict: ...

    async def run_schedule_async(self) -> JsonDict:
        """Async version of run_schedule"""
        if not self.tumbler_options:
            raise CoinjoinEmulatorError("No tumbler options provided")
        address_count = int(cast(int, self.tumbler_options.get("address_count", 3)))
        destination_addresses = [self.get_new_address() for _ in range(address_count)]

        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        json_data: JsonDict = {
            "destination_addresses": destination_addresses,
            "tumbler_options": self.tumbler_options
        }

        start = time()
        while time() - start < 60:  # Using a longer timeout for the more complex tumbler operation
            try:
                response = await self._rpc_async(method, endpoint, json_data=json_data)
                return response
            except Exception:
                if time() - start >= 60:
                    print("Failed to run schedule, attempt timed out.")
                await asyncio.sleep(1)  # Add a small delay between retries

        raise TimeoutError(f"Could not run the tumbler schedule for {self.walletname}")

    async def get_schedule_async(self) -> JsonDict:
        """Async version of get_schedule"""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        response = await self._rpc_async(method, endpoint)
        return response

    def record_round_start(
        self,
        destination: str,
        amount_sats: int | None,
        counterparties: int | None,
        mixdepth: int | None,
        current_block: int,
        chain_height: int | None = None,
    ) -> JsonDict:
        """Record a producer-owned round event for later reconciliation with the chain."""
        event = {
            "round_id": len(self.round_events) + 1,
            "engine": "joinmarket",
            "status": "started",
            "taker": self.name,
            "destination_address": destination,
            "amount_sats": amount_sats,
            "counterparties": counterparties,
            "mixdepth": mixdepth,
            "start_block": current_block,
            "start_chain_height": chain_height,
        }
        self.round_events.append(event)
        return event

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
            "destination": destination
        }
        if txfee is not None:
            json_data["txfee"] = txfee
        response = self._rpc(method, endpoint, json_data=json_data)
        return response

    async def start_coinjoin_async(
        self,
        mixdepth: int,
        amount_sats: int,
        counterparties: int,
        destination: str,
        txfee: int | None = None,
    ) -> JsonDict:
        """
        Async initiate a coinjoin as taker.
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
            "destination": destination
        }
        if txfee is not None:
            json_data["txfee"] = txfee
        response = await self._rpc_async(method, endpoint, json_data=json_data)
        return response

    def run_schedule(self) -> JsonDict:
        """
        Create and run a schedule of transactions.
        - destination_addresses: list of str, addresses to send funds to
        - tumbler_options: optional, dict, additional tumbler configuration options
        """
        if not self.tumbler_options:
            raise CoinjoinEmulatorError("No tumbler options provided")
        address_count = int(cast(int, self.tumbler_options.get("address_count", 3)))
        destination_addresses = [self.get_new_address() for _ in range(address_count)]

        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        json_data: JsonDict = {
            "destination_addresses": destination_addresses,
            "tumbler_options": self.tumbler_options
        }

        start = time()
        while time() - start < 60:  # Using a longer timeout for the more complex tumbler operation
            try:
                response = self._rpc(method, endpoint, json_data=json_data)
                return response
            except Exception:
                if time() - start >= 60:
                    print("Failed to run schedule, attempt timed out.")
                sleep(1)  # Add a small delay between retries

        raise TimeoutError(f"Could not run the tumbler schedule for {self.walletname}")

    def get_schedule(self) -> JsonDict:
        """Get the schedule that is currently running."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        response = self._rpc(method, endpoint)
        return response

    def stop_coinjoin(self) -> object:
        """Stop a running coinjoin attempt."""
        try:
            if self.type == "taker" and self.coinjoin_in_process:
                return self.stop_taker()
            if self.type == "maker" and self.maker_running:
                return self.stop_maker()
            print("No coinjoin in process")
            return True
        except Exception as e:
            print(f"Failed to stop coinjoin: {e}")
            return False

    def stop_taker(self) -> JsonDict:
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/stop"
        # When stopping not running taker, returns 401 response
        response = self._rpc(method, endpoint)
        return response

    def send(self, addressed_fundings: list[tuple[str, int]]) -> None:
        try:
            for address, amount in addressed_fundings:
                self.simple_send(destination_address=address, amount_sats=amount)
                print(f"- sent {amount} sats to {address}")
                sleep(5)  # The btc node needs time to process the transaction
        except Exception as e:
            print(f"- error during fund distribution: {e}")
            raise e

    def simple_send(
        self,
        destination_address: str,
        amount_sats: int,
        mixdepth: int = 0,
        txfee: int = 5000,
    ) -> JsonDict | bool:
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
            except Exception as e:
                print(e)
                sleep(2)

        print("Failed to send funds, attempt timed out.")

        return False
