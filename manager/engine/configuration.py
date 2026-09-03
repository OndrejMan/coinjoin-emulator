import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class JoinMarketRole(Enum):
    """JoinMarket participant roles."""
    MAKER = "maker"
    TAKER = "taker"


@dataclass
class FundConfig:
    """Configuration for individual fund when specified as an object."""
    value: int
    delay_blocks: int | None = None
    delay_rounds: int | None = None


@dataclass
class WasabiConfig:
    """Wasabi-specific wallet settings."""
    anon_score_target: int | str | None = None  # requires version >= 2.0.3
    redcoin_isolation: bool | None = None  # requires version >= 2.0.3
    skip_rounds: list[int] | None = None


@dataclass
class JoinMarketConfig:
    """JoinMarket-specific wallet settings."""
    role: JoinMarketRole | None = None
    offers: list[dict[str, Any]] | None = None
    tumbler_options: dict[str, Any] | None = None
    time_between_rounds: int | None = None
    fidelity_bond: dict[str, Any] | None = None
    max_coinjoins: int | None = None


@dataclass
class WalletConfig:
    """Wallet configuration using composition."""
    funds: list[int | FundConfig]
    
    delay_blocks: int | None = None
    delay_rounds: int | None = None
    stop_blocks: int | None = None
    stop_rounds: int | None = None
    
    version: str | None = None
    
    wasabi: WasabiConfig | None = None
    joinmarket: JoinMarketConfig | None = None


@dataclass
class ScenarioConfig:
    """Main scenario configuration."""
    name: str
    
    rounds: int  # 0 for unlimited
    blocks: int  # 0 for unlimited
    
    default_version: str
    
    wallets: list[WalletConfig]
    
    distributor_version: str | None = None
    default_anon_score_target: int | None = None
    default_redcoin_isolation: bool | None = None
    backend: dict[str, Any] | None = None

    @classmethod
    def from_json_config(cls, filepath: str | Path) -> "ScenarioConfig":
        """Load scenario configuration from JSON file."""
        with open(filepath) as f:
            data = json.load(f)
        
        # Parse wallets with engine-specific configurations
        wallets = []
        for wallet_data in data.get("wallets", []):
            wallet = cls._parse_wallet(wallet_data)
            wallets.append(wallet)
        
        return cls(
            name=data["name"],
            rounds=data["rounds"],
            blocks=data["blocks"],
            default_version=data["default_version"],
            wallets=wallets,
            distributor_version=data.get("distributor_version"),
            default_anon_score_target=data.get("default_anon_score_target"),
            default_redcoin_isolation=data.get("default_redcoin_isolation"),
            backend=data.get("backend")
        )
    
    def validate_for_engine(self, engine: str) -> None:
        """Validate the constraints that depend on the selected CoinJoin engine."""
        if engine != "joinmarket":
            return
        missing_roles = [
            str(index)
            for index, wallet in enumerate(self.wallets)
            if wallet.joinmarket is None or wallet.joinmarket.role is None
        ]
        if missing_roles:
            raise ValueError(
                "JoinMarket wallets require an explicit maker/taker role; missing at indexes: "
                + ", ".join(missing_roles)
            )

    @classmethod
    def _parse_wallet(cls, wallet_data: dict[str, Any]) -> WalletConfig:
        """Parse wallet configuration from JSON data."""
        # Parse funds (can be int or dict with value/delays)
        funds: list[int | FundConfig] = []
        for fund in wallet_data.get("funds", []):
            if isinstance(fund, int):
                funds.append(fund)
            elif isinstance(fund, dict):
                funds.append(FundConfig(
                    value=fund["value"],
                    delay_blocks=fund.get("delay_blocks"),
                    delay_rounds=fund.get("delay_rounds")
                ))
            else:
                funds.append(fund)  # fallback
        
        legacy_wasabi_fields = {"anon_score_target", "redcoin_isolation", "skip_rounds"}
        if legacy_wasabi_fields.intersection(wallet_data):
            raise ValueError("flat Wasabi wallet settings are unsupported; use the wasabi object")

        nested_wasabi = wallet_data.get("wasabi") or {}
        wasabi_fields = {
            "anon_score_target": nested_wasabi.get("anon_score_target"),
            "redcoin_isolation": nested_wasabi.get("redcoin_isolation"),
            "skip_rounds": nested_wasabi.get("skip_rounds"),
        }
        wasabi_config = None
        if any(v is not None for v in wasabi_fields.values()):
            wasabi_config = WasabiConfig(**wasabi_fields)
        
        legacy_joinmarket_fields = {
            "type",
            "offers",
            "tumbler_options",
            "time_between_rounds",
            "fidelity_bond",
            "max_coinjoins",
        }
        if legacy_joinmarket_fields.intersection(wallet_data):
            raise ValueError("flat JoinMarket wallet settings are unsupported; use the joinmarket object")

        nested_joinmarket = wallet_data.get("joinmarket") or {}
        role_value = nested_joinmarket.get("role")
        joinmarket_fields = {
            "offers": nested_joinmarket.get("offers"),
            "tumbler_options": nested_joinmarket.get("tumbler_options"),
            "time_between_rounds": nested_joinmarket.get("time_between_rounds"),
            "fidelity_bond": nested_joinmarket.get("fidelity_bond"),
            "max_coinjoins": nested_joinmarket.get("max_coinjoins"),
        }
        joinmarket_config = None
        if role_value is not None or any(value is not None for value in joinmarket_fields.values()):
            try:
                role = None if role_value is None else JoinMarketRole(str(role_value))
            except ValueError as error:
                raise ValueError(f"invalid JoinMarket role {role_value!r}") from error
            joinmarket_config = JoinMarketConfig(role=role, **joinmarket_fields)
        
        return WalletConfig(
            funds=funds,
            delay_blocks=wallet_data.get("delay_blocks"),
            delay_rounds=wallet_data.get("delay_rounds"),
            stop_blocks=wallet_data.get("stop_blocks"),
            stop_rounds=wallet_data.get("stop_rounds"),
            version=wallet_data.get("version"),
            wasabi=wasabi_config,
            joinmarket=joinmarket_config
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert the scenario configuration to a dictionary for JSON serialization."""
        def unwrap(items: list[tuple[str, Any]]) -> dict[str, Any]:
            # Enums are not JSON serializable; store the value the scenario file uses.
            return {key: value.value if isinstance(value, Enum) else value for key, value in items}

        return asdict(self, dict_factory=unwrap)


# Type aliases for convenience
FundAmount = int | FundConfig
