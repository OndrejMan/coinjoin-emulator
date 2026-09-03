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

    def display_wallet(self) -> JsonDict:
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
    def test_every_derived_address_is_flattened_from_the_wallet_display(self) -> None:
        harness = CoinsHarness(
            {
                "walletinfo": {
                    "accounts": [
                        {
                            "account": "0",
                            "branches": [
                                {
                                    "entries": [
                                        {
                                            "hd_path": "m/84'/1'/0'/0/000",
                                            "address": "bcrt1qspent",
                                            "amount": "0.00000000",
                                            "status": "used",
                                        },
                                        {
                                            "hd_path": "m/84'/1'/0'/1/000",
                                            "address": "bcrt1qchange",
                                            "amount": "0.10000000",
                                            "status": "cj-out",
                                        },
                                    ]
                                }
                            ],
                        }
                    ]
                }
            }
        )

        assert harness.list_keys() == [
            {
                "address": "bcrt1qspent",
                "path": "m/84'/1'/0'/0/000",
                "account": "0",
                "status": "used",
                "amount": "0.00000000",
            },
            {
                "address": "bcrt1qchange",
                "path": "m/84'/1'/0'/1/000",
                "account": "0",
                "status": "cj-out",
                "amount": "0.10000000",
            },
        ]

    def test_entries_without_addresses_are_skipped(self) -> None:
        harness = CoinsHarness(
            {"walletinfo": {"accounts": [{"account": "0", "branches": [{"entries": [{"address": ""}]}]}]}}
        )

        assert harness.list_keys() == []

    def test_missing_accounts_produce_an_empty_key_list(self) -> None:
        assert CoinsHarness({}).list_keys() == []
