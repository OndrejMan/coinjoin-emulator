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


def test_most_private_coin_can_pay_out_far_more_than_the_value() -> None:
    client = wasabi_client([coin("whale", 87_889_843, 9.0), coin("fits", 25_000_000, 3.0)])

    result = client.send_mixed_coins("bcrt1external", 19_800_000)

    assert result["amount_sats"] == 87_889_843


def test_amount_selection_takes_the_smallest_coin_that_covers_the_value() -> None:
    client = wasabi_client(
        [coin("whale", 87_889_843, 9.0), coin("fits", 25_000_000, 3.0), coin("short", 10_000_000, 5.0)]
    )

    result = client.send_mixed_coins("bcrt1external", 19_800_000, coin_selection="amount")

    assert [item["txid"] for item in result["coins"]] == ["fits"]
    assert result["amount_sats"] == 25_000_000


def test_amount_selection_adds_the_largest_coins_until_one_covers_the_rest() -> None:
    client = wasabi_client(
        [coin("a", 1_000_000, 9.0), coin("b", 5_000_000, 2.0), coin("c", 8_000_000, 3.0), coin("d", 6_000_000, 4.0)]
    )

    result = client.send_mixed_coins("bcrt1external", 12_000_000, coin_selection="amount")

    assert [item["txid"] for item in result["coins"]] == ["c", "b"]
    assert result["amount_sats"] == 13_000_000


def test_amount_selection_keeps_every_coin_for_all() -> None:
    client = wasabi_client([coin("a", 1_000, 5.0), coin("b", 2_000, 7.5)])

    result = client.send_mixed_coins("bcrt1external", None, coin_selection="amount")

    assert result["amount_sats"] == 3_000


def test_amount_selection_does_not_send_short_of_the_value() -> None:
    client = wasabi_client([coin("a", 3_000, 5.0), coin("b", 1_000, 7.5)])

    with pytest.raises(RuntimeError, match="4000 sats of mixed coins, 5000 sats requested"):
        client.send_mixed_coins("bcrt1external", 5_000, coin_selection="amount")

    client._rpc.assert_not_called()  # type: ignore[attr-defined]


def test_coins_the_node_sees_spent_are_skipped() -> None:
    # The wallet still lists the inputs of a coinjoin waiting in the mempool.
    client = wasabi_client(
        [coin("in-coinjoin", 9_000_000, 9.0), coin("free", 3_000_000, 4.0), coin("also-free", 2_000_000, 3.0)]
    )

    result = client.send_mixed_coins("bcrt1external", 4_000_000, unspent=lambda txid, _index: txid != "in-coinjoin")

    assert [item["txid"] for item in result["coins"]] == ["free", "also-free"]
    assert result["amount_sats"] == 5_000_000


def test_coins_spent_in_the_mempool_do_not_count_as_mixed() -> None:
    client = wasabi_client([coin("in-coinjoin", 9_000_000, 9.0), coin("free", 1_000, 4.0)])

    with pytest.raises(RuntimeError, match="1000 sats of mixed coins, 5000 sats requested"):
        client.check_mixed_coins(5_000, unspent=lambda txid, _index: txid != "in-coinjoin")


def test_all_waits_for_the_last_coinjoin_and_wallet_confirmation() -> None:
    client = wasabi_client([])
    client.version = "2.6.0"
    client.get_wallet_info = Mock(  # type: ignore[method-assign]
        side_effect=[{"coinjoinStatus": "In critical phase"}, *[{"coinjoinStatus": "Idle"}] * 3]
    )
    # A score-1 input still listed by the wallet is already spent on the node.
    # It must hold up the sweep even though mixed-coin selection would ignore it.
    client._list_unspent_coins = Mock(  # type: ignore[method-assign]
        side_effect=[
            [coin("old-red-input", 9_000, 1)],
            [coin("last-coinjoin", 8_000, 4, confirmed=False)],
            [coin("last-coinjoin", 8_000, 4)],
            [coin("last-coinjoin", 8_000, 4)],
        ]
    )
    unspent = Mock(side_effect=lambda txid, _index: txid != "old-red-input")

    with patch("manager.wasabi_clients.wasabi_client_base.sleep") as sleep:
        result = client.send_mixed_coins("bcrt1external", unspent=unspent)

    assert sleep.call_count == 3
    assert result["amount_sats"] == 8_000
    assert [item["txid"] for item in result["coins"]] == ["last-coinjoin"]


def test_all_settlement_timeout_does_not_send() -> None:
    client = wasabi_client([coin("ready", 1_000, 3)])
    client.version = "2.6.0"
    client.get_wallet_info = Mock(return_value={"coinjoinStatus": "In critical phase"})  # type: ignore[method-assign]

    with (
        patch("manager.wasabi_clients.wasabi_client_base.monotonic", side_effect=[0, 0, 301]),
        patch("manager.wasabi_clients.wasabi_client_base.sleep"),
        pytest.raises(TimeoutError, match="In critical phase"),
    ):
        client.send_mixed_coins("bcrt1external", unspent=Mock())

    client._rpc.assert_not_called()  # type: ignore[attr-defined]


def test_partial_spend_and_legacy_wasabi_do_not_wait_for_settlement() -> None:
    for version, all_coins in [("2.6.0", False), ("2.0.4", True)]:
        client = wasabi_client([coin("ready", 1_000, 3)])
        client.version = version
        client.get_wallet_info = Mock()  # type: ignore[method-assign]

        client.send_mixed_coins("bcrt1external", None if all_coins else 1, unspent=Mock(return_value=True))

        client.get_wallet_info.assert_not_called()
        assert client._rpc.call_args.args[0]["method"] == "send"  # type: ignore[attr-defined]


def test_all_settlement_deadline_also_bounds_the_node_checks() -> None:
    client = wasabi_client([coin("first", 1_000, 3), coin("second", 2_000, 4)])
    client.version = "2.6.0"
    client.get_wallet_info = Mock(return_value={"coinjoinStatus": "Idle"})  # type: ignore[method-assign]
    unspent = Mock(return_value=True)

    with (
        patch("manager.wasabi_clients.wasabi_client_base.monotonic", side_effect=[0, 0, 0, 301, 301]),
        patch("manager.wasabi_clients.wasabi_client_base.sleep"),
        pytest.raises(TimeoutError, match="checking the wallet's coins"),
    ):
        client.send_mixed_coins("bcrt1external", unspent=unspent)

    unspent.assert_called_once_with("first", 0)


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
    client.send_mixed_coins.assert_called_once_with("bcrt1external", 7, None, node.is_unspent, "anon_score")
    spend = schedule.spends[0]
    assert spend.status == "sent"
    assert (spend.sent["txid"], spend.sent["round"], spend.sent["block"], spend.sent["destination"]) == ("e" * 64, 3, 5, "bcrt1external")


def test_spend_passes_its_coin_selection_to_the_wallet() -> None:
    schedule, client, node = spending_schedule([PostmixSpendConfig(value=7, coin_selection="amount")])

    schedule.update(node, current_block=0, current_round=0)

    client.send_mixed_coins.assert_called_once_with("bcrt1external", 7, None, node.is_unspent, "amount")


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

    client.send_mixed_coins.assert_called_with("bcrt1external", None, None, node.is_unspent, "anon_score")
    assert schedule.spends[0].status == "sent"
    assert schedule.spends[0].attempts == 2


def test_spend_short_of_mixed_coins_keeps_the_wallet_mixing() -> None:
    schedule, client, node = spending_schedule([PostmixSpendConfig(value=7)])
    client.check_mixed_coins.side_effect = RuntimeError("wasabi-client-000 has 3 sats of mixed coins, 7 sats requested")

    schedule.update(node, current_block=0, current_round=0)

    client.check_mixed_coins.assert_called_once_with(7, None, node.is_unspent)
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
