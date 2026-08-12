from typing import cast

from manager.wasabi_clients.joinmarket_clients.coins import JoinMarketCoinsMixin
from manager.wasabi_clients.joinmarket_clients.types import JsonDict

SEEDPHRASE = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)


def utxo(
    txid: str = "2585ed322655adfc4645f28196b77ad7d56ab1d389eb00a044719d42995ad4c5",
    index: int = 1,
    path: str = "m/84'/1'/0'/0/0",
    value: int = 200000,
    confirmations: int = 1,
) -> JsonDict:
    return {
        "address": "bcrt1q0ldnp64tctudcfjuy89radpzecplauy7dvdf78",
        "path": path,
        "value": value,
        "mixdepth": 0,
        "confirmations": confirmations,
        "utxo": f"{txid}:{index}",
    }


class CoinsHarness(JoinMarketCoinsMixin):
    def __init__(self, *responses: JsonDict) -> None:
        self.seedphrase = SEEDPHRASE
        self.coin_history: dict[str, JsonDict] = {}
        self.responses = list(responses)
        self.error: Exception | None = None

    def list_utxos(self) -> JsonDict:
        if self.error is not None:
            raise self.error
        return self.responses.pop(0) if self.responses else {}


class TestTransformCoinsToWasabi:
    def test_utxo_is_split_into_the_wasabi_shape(self) -> None:
        harness = CoinsHarness()

        coins = harness.transform_coins_to_wasabi([utxo()])

        assert coins == [
            {
                "txid": "2585ed322655adfc4645f28196b77ad7d56ab1d389eb00a044719d42995ad4c5",
                "index": 1,
                "amount": 200000,
                "confirmed": True,
                "confirmations": 1,
                "keyPath": "84'/1'/0'/0/0",
                "address": "bcrt1q0ldnp64tctudcfjuy89radpzecplauy7dvdf78",
            }
        ]

    def test_unconfirmed_coin_is_marked_as_such(self) -> None:
        harness = CoinsHarness()

        assert harness.transform_coins_to_wasabi([utxo(confirmations=0)])[0]["confirmed"] is False

    def test_spending_transaction_is_carried_over_when_present(self) -> None:
        harness = CoinsHarness()
        coin = utxo()
        coin["spentBy"] = "spending-txid"

        assert harness.transform_coins_to_wasabi([coin])[0]["spentBy"] == "spending-txid"

    def test_unparsable_utxo_is_skipped(self) -> None:
        harness = CoinsHarness()

        assert harness.transform_coins_to_wasabi([{"utxo": "no-index"}, {"value": 1}]) == []


class TestCoinHistory:
    def test_polled_utxos_are_remembered(self) -> None:
        harness = CoinsHarness({"utxos": [utxo()]})

        harness.update_coin_history()

        assert list(harness.coin_history) == [
            "2585ed322655adfc4645f28196b77ad7d56ab1d389eb00a044719d42995ad4c5:1"
        ]

    def test_spent_coins_stay_in_the_history(self) -> None:
        harness = CoinsHarness({"utxos": [utxo()]}, {"utxos": []})

        harness.update_coin_history()
        harness.update_coin_history()

        assert len(harness.coin_history) == 1

    def test_first_record_of_a_coin_wins(self) -> None:
        harness = CoinsHarness({"utxos": [utxo(confirmations=1)]}, {"utxos": [utxo(confirmations=6)]})

        harness.update_coin_history()
        harness.update_coin_history()

        assert harness.list_coins()[0]["confirmations"] == 1

    def test_unreachable_wallet_leaves_the_history_untouched(self) -> None:
        harness = CoinsHarness()
        harness.error = Exception("wallet unreachable")

        harness.update_coin_history()

        assert harness.coin_history == {}

    def test_unspent_coins_are_read_live_and_transformed(self) -> None:
        harness = CoinsHarness({"utxos": [utxo()]})

        assert harness.list_unspent_coins()[0]["amount"] == 200000
        assert harness.coin_history == {}

    def test_unreachable_wallet_lists_no_unspent_coins(self) -> None:
        harness = CoinsHarness()
        harness.error = Exception("wallet unreachable")

        assert harness.list_unspent_coins() == []


class TestListKeys:
    def test_live_coins_are_refreshed_before_keys_are_exported(self) -> None:
        final_coinjoin_output = utxo(path="m/84'/1'/0'/1/6")
        harness = CoinsHarness({"utxos": [final_coinjoin_output]})

        keys = cast(list[JsonDict], harness.list_keys())

        assert [key["address"] for key in keys] == [final_coinjoin_output["address"]]
        assert keys[0]["full_key_path"] == "84'/1'/0'/1/6"

    def test_key_is_derived_for_every_coin_path(self) -> None:
        harness = CoinsHarness({"utxos": [utxo()]})
        harness.update_coin_history()

        keys = cast(list[JsonDict], harness.list_keys())

        assert len(keys) == 1
        assert keys[0]["full_key_path"] == "84'/1'/0'/0/0"
        assert keys[0]["internal"] is False
        assert keys[0]["address"] == "bcrt1q0ldnp64tctudcfjuy89radpzecplauy7dvdf78"
        assert isinstance(keys[0]["pubKey"], str)

    def test_change_addresses_are_marked_internal(self) -> None:
        harness = CoinsHarness({"utxos": [utxo(path="m/84'/1'/0'/1/0")]})
        harness.update_coin_history()

        keys = cast(list[JsonDict], harness.list_keys())

        assert keys[0]["internal"] is True

    def test_fidelity_bond_paths_are_skipped(self) -> None:
        harness = CoinsHarness({"utxos": [utxo(path="79:1785542400")]})
        harness.update_coin_history()

        assert harness.list_keys() == []
