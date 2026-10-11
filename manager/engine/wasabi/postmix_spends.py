"""Scheduled postmix spends: Wasabi wallets move mixed coins out of the pool once due."""

import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from manager.engine.configuration import PostmixSpendConfig, WalletConfig

POSTMIX_SPENDS_FILE = "postmix_spends.json"
POSTMIX_SPENDS_SCHEMA_VERSION = "1.0"


class SpendingClient(Protocol):
    """The Wasabi client calls a postmix spend needs."""

    name: str


@dataclass
class PostmixSpend:
    """One scheduled spend with the outcome of its attempts."""

    wallet: str
    wallet_index: int
    value: int | None
    all: bool
    delay_blocks: int
    delay_rounds: int
    min_anon_score: float | None
    status: str = "not_due"

    @classmethod
    def from_config(cls, wallet: str, wallet_index: int, config: PostmixSpendConfig) -> "PostmixSpend":
        return cls(
            wallet=wallet,
            wallet_index=wallet_index,
            value=config.value,
            all=config.all,
            delay_blocks=config.delay_blocks or 0,
            delay_rounds=config.delay_rounds or 0,
            min_anon_score=config.min_anon_score,
        )

    def record(self) -> dict[str, object]:
        """The stored form: schedule and outcome in one flat object."""
        return asdict(self)


class PostmixSpendSchedule:
    """The postmix spends of every wallet with the outcome of each spend."""

    def __init__(self, clients: Sequence[SpendingClient], wallets: list[WalletConfig]):
        self.clients = clients
        self.spends = [
            PostmixSpend.from_config(client.name, index, spend)
            for index, (client, wallet) in enumerate(zip(clients, wallets))
            for spend in (wallet.wasabi.postmix_spends if wallet.wasabi else None) or []
        ]
        if self.spends:
            print(f"- scheduled {len(self.spends)} postmix spends")

    def store(self, data_path: str) -> None:
        """Write the schedule with the outcome of each spend."""
        records = [spend.record() for spend in self.spends]
        with open(os.path.join(data_path, POSTMIX_SPENDS_FILE), "w", encoding="utf-8") as f:
            json.dump({"schema_version": POSTMIX_SPENDS_SCHEMA_VERSION, "spends": records}, f, indent=2)
        print(f"- stored {len(records)} postmix spends")
