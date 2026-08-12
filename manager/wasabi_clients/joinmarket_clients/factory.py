"""Selects and starts the JoinMarket client a wallet configuration asks for."""

from time import time
from typing import cast

from manager.engine.configuration import WalletConfig

from .joinmarket_client_base import JoinMarketClientServer
from .joinmarket_clients import MakerClient, TakerClient, TumblerTakerClient


def client_from_wallet(
    name: str,
    port: int,
    wallet: WalletConfig,
    host: str,
    proxy: str = "",
) -> JoinMarketClientServer | None:
    joinmarket = getattr(wallet, "joinmarket", None)
    type_ = joinmarket.role.value if joinmarket and joinmarket.role else "maker"
    tumbler_options = (joinmarket.tumbler_options if joinmarket else None) or {}

    # Check if wallet has fidelity bonds configured
    fidelity_bond = (joinmarket.fidelity_bond if joinmarket else None) or {}
    has_fidelity_bonds = bool(fidelity_bond.get("enabled", False))

    # Select the appropriate subclass based on the wallet config.
    client_cls: type[JoinMarketClientServer]
    if type_ == "maker":
        client_cls = MakerClient
    elif type_ == "taker":
        # Distinguish between a standard taker and a tumbler taker based on tumbler_options.
        client_cls = TumblerTakerClient if tumbler_options else TakerClient
    else:
        client_cls = JoinMarketClientServer

    # Instantiate the client using the selected subclass.
    client = client_cls(
        name=name,
        port=port,
        type=type_,
        delay=(wallet.delay_blocks or 0, wallet.delay_rounds or 0),
        stop=(wallet.stop_blocks or 0, wallet.stop_rounds or 0),
        offers=(joinmarket.offers if joinmarket else None) or [],
        tumbler_options=tumbler_options,
        time_between_rounds=(joinmarket.time_between_rounds if joinmarket else 0) or 0,
        has_fidelity_bonds=has_fidelity_bonds,
        max_coinjoins=int(cast(int, (joinmarket.max_coinjoins if joinmarket else None) or 0)),
        host=host,
        proxy=proxy
    )

    start = time()
    if not client.wait_wallet(timeout=120):
        print(
            f"- could not start {name} (application timeout {time() - start} seconds)"
        )
        return None

    print(f"- started {client.name} (wait took {time() - start} seconds)")
    return client