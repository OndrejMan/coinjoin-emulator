# pylint: disable=assignment-from-no-return,unused-argument

from time import sleep, time
from typing import TYPE_CHECKING, cast

import requests

from ...exceptions import RpcError
from .types import BTC, PASSWORD, WALLET_NAME, WALLET_TYPE, JsonDict


class JoinMarketWalletMixin:
    name: str
    walletname: str
    maker_running: bool
    coinjoin_in_process: bool

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

        def _store_tokens(self, response: JsonDict) -> None: ...

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
            "wallettype": WALLET_TYPE,
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

    def list_unspent_coins(self) -> JsonDict:
        """List all unspent coins in the wallet."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/utxos"
        response = self._rpc(method, endpoint)
        return response

    def list_coins(self) -> str:
        """List all coins in the wallet."""
        return "This method is not available in joinmarket"

    def list_keys(self) -> str:
        """List all keys in the wallet."""
        return "This method is not available in joinmarket"
