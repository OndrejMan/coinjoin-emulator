from unittest.mock import Mock, patch

import pytest

from manager.wasabi_clients.joinmarket_clients.maker import JoinMarketMakerMixin
from manager.wasabi_clients.joinmarket_clients.taker import JoinMarketTakerMixin
from manager.wasabi_clients.joinmarket_clients.types import JoinmarketConflictException, JsonDict


class RpcRecorder:
    def __init__(self, *responses: JsonDict) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, JsonDict | None]] = []
        self.error: Exception | None = None

    def _rpc(
        self,
        method: str,
        endpoint: str,
        json_data: JsonDict | None = None,
        timeout: int = 60,
        repeat: int = 4,
    ) -> JsonDict:
        self.calls.append((method, endpoint, json_data))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0) if self.responses else {}


class MakerHarness(RpcRecorder, JoinMarketMakerMixin):
    def __init__(self, *responses: JsonDict) -> None:
        super().__init__(*responses)
        self.walletname = "wallet.jmdat"
        self.maker_running = False
        self.offers: list[JsonDict] = []


class TakerHarness(RpcRecorder, JoinMarketTakerMixin):
    def __init__(self, *responses: JsonDict) -> None:
        super().__init__(*responses)
        self.name = "jcs-000"
        self.walletname = "wallet.jmdat"
        self.type = "taker"
        self.coinjoin_in_process = False
        self.maker_running = False
        self.tumbler_options: JsonDict | None = None
        self.round_events: list[JsonDict] = []
        self.addresses = ["bcrt1qone", "bcrt1qtwo", "bcrt1qthree", "bcrt1qfour"]
        self.stop_maker_calls = 0

    def get_new_address(self, mixdepth: int = 0) -> str:
        return self.addresses.pop(0)

    def stop_maker(self) -> JsonDict:
        self.stop_maker_calls += 1
        return {"stopped": "maker"}


class TestMaker:
    def test_maker_start_sends_the_offer_as_strings(self) -> None:
        harness = MakerHarness({"started": True})

        harness.start_maker(txfee=0, cjfee_a=5000, cjfee_r=4e-05, ordertype="sw0reloffer",
                            minsize=30000, maxsize=3000000)

        assert harness.calls[0][:2] == ("POST", "/wallet/wallet.jmdat/maker/start")
        assert harness.calls[0][2] == {
            "txfee": "0",
            "cjfee_a": "5000",
            "cjfee_r": "4e-05",
            "ordertype": "sw0reloffer",
            "minsize": "30000",
            "maxsize": "3000000",
        }

    def test_conflict_while_starting_returns_the_conflicting_response(self) -> None:
        harness = MakerHarness()
        response = Mock()
        harness.error = JoinmarketConflictException("no confirmed balance", response)

        assert harness.start_maker(0, 5000, 4e-05, "sw0reloffer", 30000, 3000000) is response

    def test_maker_stop_targets_the_wallet(self) -> None:
        harness = MakerHarness({"stopped": True})

        assert harness.stop_maker() == {"stopped": True}
        assert harness.calls[0] == ("GET", "/wallet/wallet.jmdat/maker/stop", None)

    def test_offers_are_served_round_robin(self) -> None:
        harness = MakerHarness()
        harness.offers = [{"minsize": 1}, {"minsize": 2}]

        assert harness.get_offer(0) == {"minsize": 1}
        assert harness.get_offer(1) == {"minsize": 2}
        assert harness.get_offer(2) == {"minsize": 1}


class TestTakerCoinjoin:
    def test_coinjoin_request_carries_the_round_parameters(self) -> None:
        harness = TakerHarness({"coinjoin": "started"})

        harness.start_coinjoin(mixdepth=0, amount_sats=35000, counterparties=4,
                               destination="bcrt1qdestination")

        assert harness.calls[0][:2] == ("POST", "/wallet/wallet.jmdat/taker/coinjoin")
        assert harness.calls[0][2] == {
            "mixdepth": 0,
            "amount_sats": 35000,
            "counterparties": 4,
            "destination": "bcrt1qdestination",
        }

    def test_transaction_fee_is_only_sent_when_configured(self) -> None:
        harness = TakerHarness({}, {})

        harness.start_coinjoin(0, 35000, 4, "bcrt1qdestination", txfee=1000)

        assert harness.calls[0][2] is not None
        assert harness.calls[0][2]["txfee"] == 1000


class TestRecordRoundStart:
    def test_recorded_event_describes_the_started_round(self) -> None:
        harness = TakerHarness()

        event = harness.record_round_start(
            destination="bcrt1qdestination",
            amount_sats=35000,
            counterparties=4,
            mixdepth=0,
            current_block=12,
            chain_height=112,
        )

        assert event == {
            "round_id": 1,
            "engine": "joinmarket",
            "status": "started",
            "taker": "jcs-000",
            "destination_address": "bcrt1qdestination",
            "amount_sats": 35000,
            "counterparties": 4,
            "mixdepth": 0,
            "start_block": 12,
            "start_chain_height": 112,
        }

    def test_round_ids_are_numbered_from_one_per_client(self) -> None:
        harness = TakerHarness()

        harness.record_round_start("bcrt1qone", 1, 1, 0, 1)
        second = harness.record_round_start("bcrt1qtwo", 1, 1, 0, 2)

        assert second["round_id"] == 2
        assert len(harness.round_events) == 2


class TestRunSchedule:
    def test_schedule_needs_tumbler_options(self) -> None:
        harness = TakerHarness()

        with pytest.raises(Exception, match="No tumbler options provided"):
            harness.run_schedule()

    def test_schedule_requests_one_destination_per_configured_address(self) -> None:
        harness = TakerHarness({"schedule": "running"})
        harness.tumbler_options = {"address_count": 2}

        harness.run_schedule()

        assert harness.calls[0][:2] == ("POST", "/wallet/wallet.jmdat/taker/schedule")
        assert harness.calls[0][2] == {
            "destination_addresses": ["bcrt1qone", "bcrt1qtwo"],
            "tumbler_options": {"address_count": 2},
        }


class TestStopCoinjoin:
    def test_running_taker_is_stopped(self) -> None:
        harness = TakerHarness({"stopped": "taker"})
        harness.coinjoin_in_process = True

        assert harness.stop_coinjoin() == {"stopped": "taker"}
        assert harness.calls[0] == ("GET", "/wallet/wallet.jmdat/taker/stop", None)

    def test_running_maker_is_stopped(self) -> None:
        harness = TakerHarness()
        harness.type = "maker"
        harness.maker_running = True

        assert harness.stop_coinjoin() == {"stopped": "maker"}
        assert harness.stop_maker_calls == 1

    def test_idle_client_is_left_alone(self) -> None:
        harness = TakerHarness()

        assert harness.stop_coinjoin() is True
        assert harness.calls == []

    def test_failure_to_stop_is_reported_as_false(self) -> None:
        harness = TakerHarness()
        harness.coinjoin_in_process = True
        harness.error = Exception("taker unreachable")

        assert harness.stop_coinjoin() is False


class TestSimpleSend:
    def test_direct_send_carries_the_amount_and_the_fee(self) -> None:
        harness = TakerHarness({"txid": "sent"})

        assert harness.simple_send("bcrt1qdestination", 50000) == {"txid": "sent"}
        assert harness.calls[0][:2] == ("POST", "/wallet/wallet.jmdat/taker/direct-send")
        assert harness.calls[0][2] == {
            "destination": "bcrt1qdestination",
            "amount_sats": 50000,
            "txfee": 5000,
            "mixdepth": 0,
        }

    def test_fund_distribution_sends_every_invoice(self) -> None:
        harness = TakerHarness({}, {})

        with patch("manager.wasabi_clients.joinmarket_clients.taker.sleep"):
            harness.send([("bcrt1qone", 1000), ("bcrt1qtwo", 2000)])

        assert [call[2] for call in harness.calls] == [
            {"destination": "bcrt1qone", "amount_sats": 1000, "txfee": 5000, "mixdepth": 0},
            {"destination": "bcrt1qtwo", "amount_sats": 2000, "txfee": 5000, "mixdepth": 0},
        ]
