from dataclasses import dataclass, asdict
from enum import Enum
from typing import cast
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
    backend: dict[str, object] | None = None
    
    @classmethod
    def from_json_config(cls, filepath: str | Path) -> "ScenarioConfig":
        """Load scenario configuration from JSON file."""
        with open(filepath, encoding="utf-8") as f:
            data = cast(dict[str, object], json.load(f))
        
        # Parse wallets with engine-specific configurations
        wallets: list[WalletConfig] = []
        raw_wallets = data.get("wallets", [])
        if not isinstance(raw_wallets, list):
            raise ValueError("wallets must be a list")
        for raw_wallet_data in raw_wallets:
            if not isinstance(raw_wallet_data, dict):
                raise ValueError("wallet configuration must be an object")
            wallet_data = cast(dict[str, object], raw_wallet_data)
            wallet = cls._parse_wallet(wallet_data)
            wallets.append(wallet)
        
        return cls(
            name=str(data["name"]),
            rounds=int(cast(int, data["rounds"])),
            blocks=int(cast(int, data["blocks"])),
            default_version=str(data["default_version"]),
            wallets=wallets,
            distributor_version=cls._optional_str(data.get("distributor_version")),
            default_anon_score_target=cls._optional_int(data.get("default_anon_score_target")),
            default_redcoin_isolation=cls._optional_bool(data.get("default_redcoin_isolation")),
            backend=cls._optional_dict(data.get("backend")),
        )
    
    @classmethod
    def _parse_wallet(cls, wallet_data: dict[str, object]) -> WalletConfig:
        """Parse wallet configuration from JSON data."""
        # Parse funds (can be int or dict with value/delays)
        funds: list[int | FundConfig] = []
        raw_funds = wallet_data.get("funds", [])
        if not isinstance(raw_funds, list):
            raise ValueError("wallet funds must be a list")
        for fund in raw_funds:
            if isinstance(fund, int):
                funds.append(fund)
            elif isinstance(fund, dict):
                fund_data = cast(dict[str, object], fund)
                funds.append(FundConfig(
                    value=int(cast(int, fund_data["value"])),
                    delay_blocks=cls._optional_int(fund_data.get("delay_blocks")),
                    delay_rounds=cls._optional_int(fund_data.get("delay_rounds")),
                ))
            else:
                raise ValueError("fund must be an integer or object")
        
        # Extract Wasabi-specific fields. Keep backward compatibility with the
        # older flat schema while supporting the generated nested schema.
        wasabi_config = None
        raw_wasabi = wallet_data.get("wasabi")
        nested_wasabi = cast(dict[str, object], raw_wasabi) if isinstance(raw_wasabi, dict) else {}
        wasabi_fields = {
            "anon_score_target": nested_wasabi.get("anon_score_target", wallet_data.get("anon_score_target")),
            "redcoin_isolation": nested_wasabi.get("redcoin_isolation", wallet_data.get("redcoin_isolation")),
            "skip_rounds": nested_wasabi.get("skip_rounds", wallet_data.get("skip_rounds"))
        }
        if any(v is not None for v in wasabi_fields.values()):
            skip_rounds = wasabi_fields["skip_rounds"]
            wasabi_config = WasabiConfig(
                anon_score_target=cast(int | str | None, wasabi_fields["anon_score_target"]),
                redcoin_isolation=cls._optional_bool(wasabi_fields["redcoin_isolation"]),
                skip_rounds=cast(list[int] | None, skip_rounds),
            )
        
        # Extract JoinMarket-specific fields, also accepting the nested schema.
        joinmarket_config = None
        raw_joinmarket = wallet_data.get("joinmarket")
        nested_joinmarket = cast(dict[str, object], raw_joinmarket) if isinstance(raw_joinmarket, dict) else {}
        role_str = nested_joinmarket.get("role", wallet_data.get("type"))
        if role_str is not None:
            role_value = role_str.value if isinstance(role_str, JoinMarketRole) else str(role_str)
            role = JoinMarketRole.MAKER if role_value == "maker" else JoinMarketRole.TAKER
            joinmarket_config = JoinMarketConfig(role=role)
        
        return WalletConfig(
            funds=funds,
            delay_blocks=cls._optional_int(wallet_data.get("delay_blocks")),
            delay_rounds=cls._optional_int(wallet_data.get("delay_rounds")),
            stop_blocks=cls._optional_int(wallet_data.get("stop_blocks")),
            stop_rounds=cls._optional_int(wallet_data.get("stop_rounds")),
            version=cls._optional_str(wallet_data.get("version")),
            wasabi=wasabi_config,
            joinmarket=joinmarket_config
        )
    
    def to_dict(self) -> dict[str, object]:
        """Convert the scenario configuration to a dictionary for JSON serialization."""
        return cast(dict[str, object], self._json_safe(asdict(self)))

    @classmethod
    def _json_safe(cls, value: object) -> object:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, list):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, dict):
            return {key: cls._json_safe(item) for key, item in value.items()}
        return value

    @staticmethod
    def _optional_int(value: object) -> int | None:
        return None if value is None else int(cast(int, value))

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _optional_bool(value: object) -> bool | None:
        return None if value is None else bool(value)

    @staticmethod
    def _optional_dict(value: object) -> dict[str, object] | None:
        return cast(dict[str, object], value) if isinstance(value, dict) else None


# Type aliases for convenience
FundAmount = int | FundConfig
