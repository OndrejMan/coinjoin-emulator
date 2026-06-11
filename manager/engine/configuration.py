from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any
import json
from pathlib import Path


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
    
    @classmethod
    def _parse_wallet(cls, wallet_data: dict[str, Any]) -> WalletConfig:
        """Parse wallet configuration from JSON data."""
        # Parse funds (can be int or dict with value/delays)
        funds = []
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
        
        # Extract Wasabi-specific fields. Keep backward compatibility with the
        # older flat schema while supporting the generated nested schema.
        wasabi_config = None
        nested_wasabi = wallet_data.get("wasabi") or {}
        wasabi_fields = {
            "anon_score_target": nested_wasabi.get("anon_score_target", wallet_data.get("anon_score_target")),
            "redcoin_isolation": nested_wasabi.get("redcoin_isolation", wallet_data.get("redcoin_isolation")),
            "skip_rounds": nested_wasabi.get("skip_rounds", wallet_data.get("skip_rounds"))
        }
        if any(v is not None for v in wasabi_fields.values()):
            wasabi_config = WasabiConfig(**wasabi_fields)
        
        # Extract JoinMarket-specific fields, also accepting the nested schema.
        joinmarket_config = None
        nested_joinmarket = wallet_data.get("joinmarket") or {}
        role_str = nested_joinmarket.get("role", wallet_data.get("type"))
        if role_str is not None:
            role_value = role_str.value if isinstance(role_str, JoinMarketRole) else str(role_str)
            role = JoinMarketRole.MAKER if role_value == "maker" else JoinMarketRole.TAKER
            joinmarket_config = JoinMarketConfig(role=role)
        
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
        return asdict(self)


# Type aliases for convenience
FundAmount = int | FundConfig
