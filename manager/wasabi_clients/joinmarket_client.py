import json
from time import sleep, time
from typing import cast

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from ..exceptions import RpcError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


WALLET_NAME = "wallet"
PASSWORD = "password"
WALLET_TYPE = "sw"
BTC = 100_000_000
JsonDict = dict[str, object]


class JoinmarketConflictException(Exception):
    def __init__(self, message: str, response: requests.Response) -> None:
        super().__init__(message)
        self.response = response



class JoinMarketClientServer:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 28183,
        walletname: str = WALLET_NAME,
        name: str = "joinmarket-client-server",
        proxy: str = "",
        version: str = "",
        role: str = "maker",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
    ) -> None:
        self.host = host
        self.port = port
        self.walletname = walletname  # Store walletname as an instance variable
        self.name = name
        self.proxy = proxy
        self.version = version
        self.role = role
        self.maker_running = False
        self.coinjoin_in_process = False
        self.coinjoin_start = 0
        self.delay = delay
        self.stop = stop
        self.token = ""
        self.refresh_token = ""

    @property
    def type(self) -> str:
        return self.role

    @type.setter
    def type(self, role: str) -> None:
        self.role = role

    def _headers(self, auth_required: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {}
        if auth_required and self.token:
            headers['Authorization'] = f'Bearer {self.token}'
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

    def get_status(self) -> JsonDict:
        method = "GET"
        endpoint = "/session"
        response = self._rpc(method, endpoint, auth_required=False)
        self.maker_running = bool(response.get("maker_running", False))
        self.coinjoin_in_process = bool(response.get("coinjoin_in_process", False))
        return response

    def _create_wallet(self, walletname: str | None = None) -> JsonDict:
        """Create a new wallet and store its name."""
        method = "POST"
        endpoint = "/wallet/create"
        self.walletname = walletname or self.walletname or WALLET_NAME
        data: JsonDict = {
            "walletname": self.walletname,
            "password": PASSWORD,
            "wallettype": WALLET_TYPE
        }
        response = self._rpc(method, endpoint, json_data=data, auth_required=False)
        self._store_tokens(response)
        return response

    def unlock_wallet(self, password: str | None = None) -> JsonDict:
        """Unlock an existing wallet using the stored walletname."""
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/unlock"
        json_data: JsonDict = {"password": password or PASSWORD}
        response = self._rpc(method, endpoint, json_data=json_data, auth_required=False)
        self._store_tokens(response)
        return response


    def wait_wallet(self, timeout: int | None = None) -> bool:
        start = time()
        last_create_err = None
        last_balance_err = None
        while timeout is None or time() - start < timeout:
            try:
                self._create_wallet()
            except (requests.exceptions.RequestException, RpcError, TimeoutError, KeyError, TypeError, ValueError) as e:
                last_create_err = e

            try:
                self.get_balance()
                return True
            except (requests.exceptions.RequestException, RpcError, TimeoutError, KeyError, TypeError, ValueError) as e:
                last_balance_err = e

            sleep(0.1)
        print(f"- {self.name} wait_wallet timed out after {timeout}s.")
        print(f"  Last create error: {last_create_err}")
        print(f"  Last balance error: {last_balance_err}")
        return False


    def display_wallet(self) -> JsonDict:
        """Get detailed breakdown of wallet contents by account."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/display"
        response = self._rpc(method, endpoint)
        return response

    def get_balance(self) -> int:
        """Retrieve the available balance of the wallet.
        Returns: str: The available balance as a string in BTC (e.g., '0.00000000').
        Raises: Exception: If the balance information cannot be retrieved.
        """
        response = self.display_wallet()
        try:
            walletinfo = cast(JsonDict, response["walletinfo"])
            available_balance = walletinfo["available_balance"]
            return int(float(str(available_balance)) * BTC)
        except KeyError as e:
            raise RpcError(f"Could not retrieve available balance: {e}") from e

    def get_yieldgen_report(self) -> JsonDict:
        """Get the latest report on yield-generating activity."""
        method = "GET"
        endpoint = "/wallet/yieldgen/report"
        response = self._rpc(method, endpoint)
        return response

    def get_new_address(self, mixdepth: int = 0) -> str:
        """Get a fresh address in the given account for depositing funds."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/address/new/{mixdepth}"
        response = self._rpc(method, endpoint)
        return str(response["address"])

    def get_new_timelock_address(self, lockdate: str) -> JsonDict:
        """Get a fresh timelock address for depositing funds to create a fidelity bond."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/address/timelock/new/{lockdate}"
        response = self._rpc(method, endpoint)
        return response

    def list_utxos(self) -> JsonDict:
        """List details of all UTXOs currently in the wallet."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/utxos"
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
            "minsize": str(minsize)
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
            return self.stop_taker()
        if self.role == "maker" and self.maker_running:
            return self.stop_maker()
        print("No coinjoin in process")
        return True

    def stop_taker(self) -> JsonDict:
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/stop"
        # When stopping not running taker, returns 401 response
        response = self._rpc(method, endpoint)
        return response

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

    def list_unspent_coins(self) -> JsonDict:
        """List all unspent coins in the wallet."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/utxos"
        response = self._rpc(method, endpoint)
        return response

    def list_transactions_maker(self) -> JsonDict:
        """List all transactions in the wallet."""
        method = "GET"
        endpoint = "/wallet/yieldgen/report"
        response = self._rpc(method, endpoint)
        return response


    def list_coins(self) -> str:
        """List all coins in the wallet."""
        return "This method is not available in joinmarket"
        # method = "GET"
        # endpoint = f"/wallet/{self.walletname}/coins"
        # response = self._rpc(method, endpoint)
        # return response

    def list_keys(self) -> str:
        """List all keys in the wallet."""
        return "This method is not available in joinmarket"
        # method = "GET"
        # endpoint = f"/wallet/{self.walletname}/keys"
        # response = self._rpc(method, endpoint)
        # return response
