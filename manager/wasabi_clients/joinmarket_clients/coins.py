"""Coin and key listings, in the shape the Wasabi-oriented engine expects."""

from typing import TYPE_CHECKING, cast

from bip_utils import Bip32Slip10Secp256k1, Bip39SeedGenerator

from .types import JsonDict


class JoinMarketCoinsMixin:
    """Keeps the UTXO history and renders it the way the engine stores it."""

    seedphrase: str
    coin_history: dict[str, JsonDict]

    if TYPE_CHECKING:
        def list_utxos(self) -> JsonDict: ...
        async def list_utxos_async(self) -> JsonDict: ...

    async def update_coin_history_async(self) -> None:
        """
        Async version: Poll the current unspent coins (UTXOs) from the API and update the internal
        coin history. Expects the API to return a dict with a key "utxos" that is a list
        of coin dicts.
        """
        try:
            response = await self.list_utxos_async()
            # Extract the list of coins from the JSON structure.
            coins = response.get("utxos", [])
        except Exception as e:
            print(f"Error fetching UTXOs: {e}")
            return

        for coin in cast(list[JsonDict], coins):
            key = str(coin.get("utxo") or "")
            if key:
                # setdefault ensures we record a coin only once
                self.coin_history.setdefault(key, coin)

    def list_unspent_coins(self) -> list[JsonDict]:
        """List all unspent coins in the wallet."""
        try:
            response = self.list_utxos()
            coins = cast(list[JsonDict], response.get("utxos", []))
        except Exception as e:
            print("Error fetching UTXOs:", e)
            return []
        return self.transform_coins_to_wasabi(coins)

    def list_coins(self) -> list[JsonDict]:
        """List all coins in the wallet."""
        return self.transform_coins_to_wasabi(
            list(self.coin_history.values()))

    def list_keys(self) -> object:
        """List all keys in the wallet."""
        seed_bytes = Bip39SeedGenerator(self.seedphrase).Generate()
        coins = self.list_coins()
        keys: list[JsonDict] = []
        for coin in coins:
            key_path = str(coin.get("keyPath", ""))

            # Skip fidelity bond coins that have colons in their paths (e.g., "79:1785542400")
            # These are not valid BIP32 paths and are handled differently in JoinMarket
            if ":" in key_path:
                print(f"Skipping fidelity bond coin with path: {key_path}")
                continue

            # Skip empty paths
            if not key_path:
                continue

            key: JsonDict = {"full_key_path": key_path}
            try:
                bip32_ctx = Bip32Slip10Secp256k1.FromSeedAndPath(seed_bytes, str(key_path))
                key["pubKey"] = bip32_ctx.PublicKey().RawUncompressed().ToHex()
                key["internal"] = str(key_path).split("/")[-2] == "1"
                key["address"] = coin.get("address", "")
                keys.append(key)
            except Exception as e:
                print(f"Error processing key path '{key_path}': {e}")
                continue

        return keys

    def update_coin_history(self) -> None:
        """
        Poll the current unspent coins (UTXOs) from the API and update the internal
        coin history. Expects the API to return a dict with a key "utxos" that is a list
        of coin dicts.
        """
        try:
            response = self.list_utxos()
            # Extract the list of coins from the JSON structure.
            coins = response.get("utxos", [])
        except Exception as e:
            print("Error fetching UTXOs:", e)
            return

        for coin in cast(list[JsonDict], coins):
            utxo = str(coin.get("utxo") or "")
            if utxo:
                # setdefault ensures we record a coin only once
                self.coin_history.setdefault(utxo, coin)

    def transform_coins_to_wasabi(self, joinmarket_coins: list[JsonDict]) -> list[JsonDict]:
        """
        Transform joinmarket's UTXO output to the Wasabi Wallet format.

        Expected joinmarket coin format (example):
        {
            "address": "bcrt1q0ldnp64tctudcfjuy89radpzecplauy7dvdf78",
            "path": "m/84'/1'/0'/0/0",
            "label": "",
            "value": 200000,
            "tries": 0,
            "tries_remaining": 3,
            "external": False,
            "mixdepth": 0,
            "confirmations": 1,
            "frozen": False,
            "utxo": "2585ed322655adfc4645f28196b77ad7d56ab1d389eb00a044719d42995ad4c5:1"
        }

        Desired Wasabi format (example):
        {
            "txid": "2585ed322655adfc4645f28196b77ad7d56ab1d389eb00a044719d42995ad4c5",
            "index": 1,
            "amount": 200000,
            "anonymityScore": 1,
            "confirmed": true,
            "confirmations": 1,
            "keyPath": "84'/1'/0'/0/0",
            "address": "bcrt1q0ldnp64tctudcfjuy89radpzecplauy7dvdf78"
        }
        """
        wasabi_coins = []
        for coin in joinmarket_coins:
            utxo_str = str(coin.get("utxo", ""))
            if not utxo_str:
                continue
            try:
                txid, index_str = utxo_str.split(":")
                index = int(index_str)
            except Exception as e:
                print(f"Could not parse utxo '{utxo_str}': {e}")
                continue

            key_path = str(coin.get("path", ""))
            if key_path.startswith("m/"):
                key_path = key_path[2:]

            confirmations = int(cast(int, coin.get("confirmations", 0)))
            wasabi_coin: JsonDict = {
                "txid": txid,
                "index": index,
                "amount": coin.get("value"),
                "confirmed": confirmations > 0,
                "confirmations": confirmations,
                "keyPath": key_path,
                "address": coin.get("address"),
            }
            if "spentBy" in coin:
                wasabi_coin["spentBy"] = coin["spentBy"]

            wasabi_coins.append(wasabi_coin)
        return wasabi_coins
