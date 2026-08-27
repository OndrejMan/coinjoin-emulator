from ..configuration import (
    JoinMarketConfig,
    JoinMarketRole,
    ScenarioConfig,
    WalletConfig,
)


def default_joinmarket_scenario() -> ScenarioConfig:
    return ScenarioConfig(
        name="default",
        default_version="joinmarket",
        rounds=5,
        blocks=0,
        wallets=[
            WalletConfig(
                funds=[200000, 50000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.TAKER),
            ),
            WalletConfig(
                funds=[3000000],
                delay_blocks=2,
                joinmarket=JoinMarketConfig(role=JoinMarketRole.TAKER),
            ),
            WalletConfig(
                funds=[1000000, 500000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
            WalletConfig(
                funds=[3000000, 15000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
            WalletConfig(
                funds=[1000000, 500000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
            WalletConfig(
                funds=[3000000, 600000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
            WalletConfig(
                funds=[200000, 50000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
            WalletConfig(
                funds=[3000000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
            WalletConfig(
                funds=[1000000, 500000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
            WalletConfig(
                funds=[3000000, 15000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
            WalletConfig(
                funds=[1000000, 500000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
            WalletConfig(
                funds=[3000000, 600000],
                joinmarket=JoinMarketConfig(role=JoinMarketRole.MAKER),
            ),
        ],
    )
