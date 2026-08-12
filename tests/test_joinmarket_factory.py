from unittest.mock import patch

from manager.engine.configuration import JoinMarketConfig, JoinMarketRole, WalletConfig
from manager.wasabi_clients.joinmarket_clients.factory import client_from_wallet
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer


def make_client(role: JoinMarketRole, offers: list[dict[str, object]] | None = None) -> JoinMarketClientServer:
    wallet = WalletConfig(
        funds=[100_000],
        joinmarket=JoinMarketConfig(role=role, offers=offers or []),
    )
    with patch.object(JoinMarketClientServer, "wait_wallet", return_value=True):
        client = client_from_wallet("client", 28183, wallet, "localhost")
    assert client is not None
    return client


def test_legacy_maker_without_offers_uses_main_defaults() -> None:
    client = make_client(JoinMarketRole.MAKER)

    assert client.offers == [{
        "txfee": 0,
        "cjfee_a": 5000,
        "cjfee_r": 0.00004,
        "ordertype": "sw0reloffer",
        "minsize": 30000,
        "maxsize": 3000000,
    }]


def test_legacy_taker_without_offers_uses_main_defaults() -> None:
    client = make_client(JoinMarketRole.TAKER)

    assert client.offers == [{"mixdepth": 0, "amount_sats": 40000, "counterparties": 4}]


def test_explicit_offers_take_precedence_over_legacy_defaults() -> None:
    offer: dict[str, object] = {
        "mixdepth": 2,
        "amount_sats": 75_000,
        "counterparties": 5,
    }

    client = make_client(JoinMarketRole.TAKER, [offer])

    assert client.offers == [offer]
    assert client.offers[0] is not offer
