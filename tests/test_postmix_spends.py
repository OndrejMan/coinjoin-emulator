"""Scheduled postmix spends: wallets move mixed coins out of the pool once due."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from manager.engine.configuration import PostmixSpendConfig, WalletConfig, WasabiConfig
from manager.engine.wasabi.postmix_spends import POSTMIX_RETRY_SECONDS, PostmixSpendSchedule
from manager.wasabi_clients.wasabi_client_base import WasabiClientBase


def coin(txid: str, amount: int, score: float, confirmed: bool = True) -> dict[str, object]:
    return {"txid": txid, "index": 0, "amount": amount, "anonymityScore": score, "confirmed": confirmed}


def wasabi_client(coins: list[dict[str, object]]) -> WasabiClientBase:
    client = WasabiClientBase(name="wasabi-client-001")
    client._list_unspent_coins = Mock(return_value=coins)  # type: ignore[method-assign]
    client._rpc = Mock(return_value={"txid": "f" * 64, "tx": "00"})  # type: ignore[method-assign]
    return client


def sent_request(client: WasabiClientBase) -> dict[str, object]:
    return client._rpc.call_args.args[0]["params"]  # type: ignore[attr-defined, no-any-return]


def test_most_private_mixed_coins_cover_the_value_without_change() -> None:
    client = wasabi_client(
        [coin("fresh", 9_000_000, 1.0), coin("low", 3_000_000, 4.0), coin("high", 2_000_000, 9.0)]
    )

    result = client.send_mixed_coins("bcrt1external", 4_000_000)

    params = sent_request(client)
    assert params["coins"] == [{"transactionid": "high", "index": 0}, {"transactionid": "low", "index": 0}]
    assert params["payments"] == [
        {"sendto": "bcrt1external", "amount": 5_000_000, "label": "postmix", "subtractFee": True}
    ]
    assert result["txid"] == "f" * 64
    assert result["amount_sats"] == 5_000_000


def test_all_spends_every_confirmed_coin_at_the_threshold() -> None:
    client = wasabi_client(
        [coin("a", 1_000, 5.0), coin("b", 2_000, 7.5), coin("c", 4_000, 4.9), coin("d", 8_000, 9.0, confirmed=False)]
    )

    result = client.send_mixed_coins("bcrt1external", None, min_anon_score=5)

    assert [item["txid"] for item in result["coins"]] == ["b", "a"]
    assert result["amount_sats"] == 3_000


def test_insufficient_mixed_coins_do_not_send() -> None:
    client = wasabi_client([coin("fresh", 9_000_000, 1.0), coin("mixed", 1_000, 3.0)])

    with pytest.raises(RuntimeError, match="1000 sats of mixed coins, 5000 sats requested"):
        client.send_mixed_coins("bcrt1external", 5_000)

    client._rpc.assert_not_called()  # type: ignore[attr-defined]


def spending_schedule(spends: list[PostmixSpendConfig]) -> tuple[PostmixSpendSchedule, Mock, Mock]:
    node = Mock()
    node.get_new_address.return_value = "bcrt1external"
    client = Mock()
    client.name = "wasabi-client-000"
    client.send_mixed_coins.return_value = {"txid": "e" * 64, "amount_sats": 7, "coins": []}
    schedule = PostmixSpendSchedule([client], [WalletConfig(funds=[1], wasabi=WasabiConfig(postmix_spends=spends))])
    return schedule, client, node


def test_spend_waits_for_both_delays_then_stops_mixing_and_sends() -> None:
    schedule, client, node = spending_schedule([PostmixSpendConfig(value=7, delay_rounds=3, delay_blocks=5)])

    schedule.update(node, current_block=4, current_round=3)
    client.send_mixed_coins.assert_not_called()

    schedule.update(node, current_block=5, current_round=3)
    schedule.update(node, current_block=5, current_round=3)

    client.stop_coinjoin.assert_called_once_with()
    client.send_mixed_coins.assert_called_once_with("bcrt1external", 7, None)
    spend = schedule.spends[0]
    assert spend.status == "sent"
    assert (spend.sent["txid"], spend.sent["round"], spend.sent["block"], spend.sent["destination"]) == ("e" * 64, 3, 5, "bcrt1external")


def test_failed_spend_is_retried_after_a_pause() -> None:
    schedule, client, node = spending_schedule([PostmixSpendConfig(all=True)])
    client.send_mixed_coins.side_effect = [RuntimeError("coin in round"), {"txid": "d" * 64, "amount_sats": 1, "coins": []}]

    with patch(
        "manager.engine.wasabi.postmix_spends.time.time",
        side_effect=[100.0, 100.0, 101.0, 100.0 + POSTMIX_RETRY_SECONDS],
    ):
        schedule.update(node, 0, 0)
        assert schedule.spends[0].status == "failed"
        assert schedule.spends[0].last_error == "coin in round"
        schedule.update(node, 0, 0)
        assert client.send_mixed_coins.call_count == 1
        schedule.update(node, 0, 0)

    client.send_mixed_coins.assert_called_with("bcrt1external", None, None)
    assert schedule.spends[0].status == "sent"
    assert schedule.spends[0].attempts == 2


def test_spend_short_of_mixed_coins_keeps_the_wallet_mixing() -> None:
    schedule, client, node = spending_schedule([PostmixSpendConfig(value=7)])
    client.check_mixed_coins.side_effect = RuntimeError("wasabi-client-000 has 3 sats of mixed coins, 7 sats requested")

    schedule.update(node, current_block=0, current_round=0)

    client.check_mixed_coins.assert_called_once_with(7, None)
    client.stop_coinjoin.assert_not_called()
    client.send_mixed_coins.assert_not_called()
    assert schedule.spends[0].status == "failed"


def test_stored_schedule_records_every_outcome(tmp_path: Path) -> None:
    schedule, _, node = spending_schedule([PostmixSpendConfig(value=7), PostmixSpendConfig(all=True, delay_rounds=99)])
    schedule.update(node, current_block=0, current_round=1)

    schedule.store(str(tmp_path))

    stored = json.loads((tmp_path / "postmix_spends.json").read_text())
    assert [spend["status"] for spend in stored["spends"]] == ["sent", "not_due"]
    assert (stored["spends"][0]["txid"], stored["spends"][0]["attempts"]) == ("e" * 64, 1)
    assert "next_attempt_at" not in stored["spends"][0]


def test_stored_schedule_lists_every_spend(tmp_path: Path) -> None:
    client = SimpleNamespace(name="wasabi-client-000")
    spends = [PostmixSpendConfig(value=7), PostmixSpendConfig(all=True, delay_rounds=99)]
    schedule = PostmixSpendSchedule([client], [WalletConfig(funds=[1], wasabi=WasabiConfig(postmix_spends=spends))])

    schedule.store(str(tmp_path))

    stored = json.loads((tmp_path / "postmix_spends.json").read_text())
    assert stored["schema_version"] == "1.0"
    assert [(spend["value"], spend["all"], spend["delay_rounds"]) for spend in stored["spends"]] == [
        (7, False, 0),
        (None, True, 99),
    ]
    assert {spend["wallet"] for spend in stored["spends"]} == {"wasabi-client-000"}
    assert {spend["status"] for spend in stored["spends"]} == {"not_due"}


def test_wallets_without_a_schedule_add_nothing() -> None:
    clients = [SimpleNamespace(name="wasabi-client-000"), SimpleNamespace(name="wasabi-client-001")]

    schedule = PostmixSpendSchedule(
        clients, [WalletConfig(funds=[1]), WalletConfig(funds=[1], wasabi=WasabiConfig(anon_score_target=5))]
    )

    assert schedule.spends == []
