"""Offer resolution when a scenario only declares a JoinMarket role."""

from manager.engine.configuration import JoinMarketConfig, JoinMarketRole
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer


def test_a_maker_without_offers_gets_the_legacy_default_offer() -> None:
    config = JoinMarketConfig(role=JoinMarketRole.MAKER)

    offers = JoinMarketClientServer.offers_for_wallet(config, "maker")

    assert len(offers) == 1
    assert offers[0]["ordertype"] == "sw0reloffer"


def test_a_taker_without_offers_gets_the_legacy_default_order() -> None:
    config = JoinMarketConfig(role=JoinMarketRole.TAKER)

    assert JoinMarketClientServer.offers_for_wallet(config, "taker") == [
        {"mixdepth": 0, "amount_sats": 40000, "counterparties": 4}
    ]


def test_configured_offers_are_kept_and_copied() -> None:
    configured = [{"ordertype": "swreloffer", "minsize": 1}]
    config = JoinMarketConfig(role=JoinMarketRole.MAKER, offers=configured)

    offers = JoinMarketClientServer.offers_for_wallet(config, "maker")

    assert offers == configured
    offers[0]["minsize"] = 2
    assert configured[0]["minsize"] == 1
