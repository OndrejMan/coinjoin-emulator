"""Postmix spends of JoinMarket wallets: coinjoin outputs leave the pool one mixdepth at a time."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from manager.engine.configuration import JoinMarketConfig, JoinMarketRole, PostmixSpendConfig, WalletConfig
from manager.engine.joinmarket.postmix import JoinMarketPostmixWallet
from manager.engine.joinmarket_engine import JoinmarketEngine
from manager.engine.postmix_spends import PostmixSpendSchedule

COINJOINS = {"cj1", "cj2"}


def utxo(txid: str, value: int, mixdepth: int, confirmations: int = 1, frozen: bool = False) -> dict[str, object]:
    return {
        "utxo": f"{txid}:0",
        "value": value,
        "mixdepth": mixdepth,
        "confirmations": confirmations,
        "frozen": frozen,
    }


def jm_wallet(coins: list[dict[str, object]], role: str = "maker") -> tuple[JoinMarketPostmixWallet, Mock]:
    client = Mock()
    client.name = "jcs-000"
    client.type = role
    client.session.return_value = {"maker_running": False, "coinjoin_in_process": False}
    client.list_utxos.return_value = {"utxos": coins}

    def sweep(destination: str, mixdepth: int) -> dict[str, object]:
        frozen = {call.args[0] for call in client.freeze_utxo.call_args_list if call.args[1]}
        inputs = [c["utxo"] for c in coins if c["mixdepth"] == mixdepth and not c["frozen"] and c["utxo"] not in frozen]
        return {"txid": f"sweep-{mixdepth}", "inputs": [{"outpoint": item} for item in inputs]}

    client.sweep_mixdepth.side_effect = sweep
    return JoinMarketPostmixWallet(client, lambda: COINJOINS), client


def test_value_is_covered_from_one_mixdepth_with_the_other_coins_frozen() -> None:
    wallet, client = jm_wallet(
        [utxo("cj1", 300_000, 1), utxo("fresh", 900_000, 1), utxo("cj2", 150_000, 0), utxo("cj2b", 1, 0)]
    )

    result = wallet.send_mixed_coins("bcrt1external", 200_000)

    client.sweep_mixdepth.assert_called_once_with("bcrt1external", 1)
    assert [call.args for call in client.freeze_utxo.call_args_list] == [("fresh:0", True), ("fresh:0", False)]
    assert (result["txid"], result["txids"], result["amount_sats"]) == ("sweep-1", ["sweep-1"], 300_000)
    assert result["coins"] == [{"txid": "cj1", "index": 0, "amount": 300_000, "mixdepth": 1}]


def test_mixdepth_with_the_least_overshoot_pays_the_value() -> None:
    wallet, client = jm_wallet([utxo("cj1", 900_000, 0), utxo("cj2", 250_000, 2)])

    wallet.send_mixed_coins("bcrt1external", 200_000)

    client.sweep_mixdepth.assert_called_once_with("bcrt1external", 2)


def test_all_sweeps_every_mixdepth_holding_mixed_coins() -> None:
    wallet, client = jm_wallet([utxo("cj1", 100_000, 0), utxo("cj2", 200_000, 3), utxo("fresh", 5, 1)])

    result = wallet.send_mixed_coins("bcrt1external", None)

    assert [call.args for call in client.sweep_mixdepth.call_args_list] == [("bcrt1external", 0), ("bcrt1external", 3)]
    assert (result["txid"], result["txids"], result["amount_sats"]) == ("sweep-0", ["sweep-0", "sweep-3"], 300_000)


def test_mixdepths_are_never_merged_to_cover_a_value() -> None:
    wallet, client = jm_wallet([utxo("cj1", 100_000, 0), utxo("cj2", 100_000, 1)])

    with pytest.raises(RuntimeError, match="at most 100000 sats of mixed coins in one mixdepth, 150000 sats requested"):
        wallet.check_mixed_coins(150_000)

    client.sweep_mixdepth.assert_not_called()


def test_unconfirmed_frozen_and_mempool_spent_outputs_are_not_mixed() -> None:
    coins = [utxo("cj1", 100_000, 0, confirmations=0), utxo("cj2", 100_000, 1, frozen=True)]
    wallet, _ = jm_wallet(coins + [utxo("cj1", 100_000, 2) | {"utxo": "cj1:5"}])

    with pytest.raises(RuntimeError, match="has no mixed coins"):
        wallet.check_mixed_coins(None, unspent=lambda txid, index: index != 5)


def test_coins_are_unfrozen_when_the_sweep_fails() -> None:
    wallet, client = jm_wallet([utxo("cj1", 100_000, 0), utxo("fresh", 7, 0)])
    client.sweep_mixdepth.side_effect = RuntimeError("Error 409")

    with pytest.raises(RuntimeError, match="409"):
        wallet.send_mixed_coins("bcrt1external", 50_000)

    assert [call.args for call in client.freeze_utxo.call_args_list] == [("fresh:0", True), ("fresh:0", False)]


def test_maker_is_stopped_and_awaited_before_spending() -> None:
    wallet, client = jm_wallet([])
    client.session.side_effect = [{"maker_running": True}, {"maker_running": False, "coinjoin_in_process": False}]

    with patch("manager.engine.joinmarket.postmix.time.sleep") as sleep:
        wallet.stop_coinjoin()

    client.stop_maker.assert_called_once_with()
    sleep.assert_called_once()


def test_running_taker_coinjoin_is_not_cut_short() -> None:
    wallet, client = jm_wallet([], role="taker")
    client.session.return_value = {"maker_running": False, "coinjoin_in_process": True}

    with pytest.raises(RuntimeError, match="jcs-000 is in a coinjoin"):
        wallet.stop_coinjoin()

    client.stop_maker.assert_not_called()


def test_engine_schedules_joinmarket_spends_against_confirmed_coinjoins() -> None:
    engine = JoinmarketEngine.__new__(JoinmarketEngine)
    taker = SimpleNamespace(
        name="jcs-000",
        round_events=[
            {"status": "confirmed", "destination_matches": [{"txid": "cj1", "block_height": 7}]},
            {"status": "failed", "destination_matches": []},
        ],
    )
    engine.clients = [taker, SimpleNamespace(name="jcs-001", round_events=[])]
    spends = [PostmixSpendConfig(all=True, coin_selection="amount")]
    wallets = [
        WalletConfig(funds=[1], joinmarket=JoinMarketConfig(role=JoinMarketRole.TAKER)),
        WalletConfig(funds=[1], joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER, postmix_spends=spends)),
    ]

    engine.prepare_wallet_schedules(wallets)

    assert engine.confirmed_coinjoin_txids() == {"cj1"}
    assert isinstance(engine.postmix_spends, PostmixSpendSchedule)
    assert [(spend.wallet, spend.wallet_index, spend.coin_selection) for spend in engine.postmix_spends.spends] == [
        ("jcs-001", 1, "amount")
    ]
