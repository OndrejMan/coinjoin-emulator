import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import cast


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
    offers: list[dict[str, object]] | None = None
    tumbler_options: dict[str, object] | None = None
    time_between_rounds: int | None = None
    fidelity_bond: dict[str, object] | None = None
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
    backend: dict[str, object] | None = None
    
    @classmethod
    def from_json_config(cls, filepath: str | Path) -> "ScenarioConfig":
        """Load scenario configuration from JSON file."""
        with open(filepath, encoding="utf-8") as f:
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
    
    @classmethod
    def _parse_wallet(cls, wallet_data: dict[str, object]) -> WalletConfig:
        """Parse wallet configuration from JSON data."""
        # Parse funds (can be int or dict with value/delays)
        funds: list[int | FundConfig] = []
        raw_funds = wallet_data.get("funds", [])
        for fund in cast(list[object], raw_funds if isinstance(raw_funds, list) else []):
            if isinstance(fund, int):
                funds.append(fund)
            elif isinstance(fund, dict):
                fund_data = cast(dict[str, object], fund)
                funds.append(FundConfig(
                    value=cast(int, fund_data["value"]),
                    delay_blocks=cast(int | None, fund_data.get("delay_blocks")),
                    delay_rounds=cast(int | None, fund_data.get("delay_rounds")),
                ))
            else:
                raise ValueError(f"Unexpected fund entry: {fund!r}")
        
        # Extract Wasabi-specific fields
        wasabi_config = None
        wasabi_fields = {
            "anon_score_target": wallet_data.get("anon_score_target"),
            "redcoin_isolation": wallet_data.get("redcoin_isolation"),
            "skip_rounds": wallet_data.get("skip_rounds")
        }
        if any(v is not None for v in wasabi_fields.values()):
            wasabi_config = WasabiConfig(
                anon_score_target=cast(int | str | None, wasabi_fields["anon_score_target"]),
                redcoin_isolation=cast(bool | None, wasabi_fields["redcoin_isolation"]),
                skip_rounds=cast(list[int] | None, wasabi_fields["skip_rounds"]),
            )
        
        # Extract JoinMarket-specific fields
        joinmarket_config = None
        if "type" in wallet_data:
            role_str = wallet_data["type"]
            role = JoinMarketRole.MAKER if role_str == "maker" else JoinMarketRole.TAKER
            joinmarket_config = JoinMarketConfig(
                role=role,
                offers=cast(list[dict[str, object]] | None, wallet_data.get("offers")),
                tumbler_options=cast(dict[str, object] | None, wallet_data.get("tumbler_options")),
                time_between_rounds=cast(int | None, wallet_data.get("time_between_rounds")),
                fidelity_bond=cast(dict[str, object] | None, wallet_data.get("fidelity_bond")),
                max_coinjoins=cast(int | None, wallet_data.get("max_coinjoins")),
            )
        
        return WalletConfig(
            funds=funds,
            delay_blocks=cast(int | None, wallet_data.get("delay_blocks")),
            delay_rounds=cast(int | None, wallet_data.get("delay_rounds")),
            stop_blocks=cast(int | None, wallet_data.get("stop_blocks")),
            stop_rounds=cast(int | None, wallet_data.get("stop_rounds")),
            version=cast(str | None, wallet_data.get("version")),
            wasabi=wasabi_config,
            joinmarket=joinmarket_config
        )
    
    def to_dict(self) -> dict[str, object]:
        """Convert the scenario configuration to a dictionary for JSON serialization."""
        def unwrap(items: list[tuple[str, object]]) -> dict[str, object]:
            # Enums are not JSON serializable; store the value the scenario file uses.
            return {key: value.value if isinstance(value, Enum) else value for key, value in items}

        return asdict(self, dict_factory=unwrap)


# Type aliases for convenience
FundAmount = int | FundConfig
