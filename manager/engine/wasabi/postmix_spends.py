"""Scheduled postmix spends: Wasabi wallets move mixed coins out of the pool once due."""

import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Protocol

from manager.engine.configuration import PostmixSpendConfig, WalletConfig

POSTMIX_SPENDS_FILE = "postmix_spends.json"
POSTMIX_SPENDS_SCHEMA_VERSION = "1.0"
POSTMIX_RETRY_SECONDS = 30


class FundingNode(Protocol):
    """The node RPC that provides a destination outside every mixing wallet."""

    def get_new_address(self) -> str:
        """Return a fresh address of the funding wallet."""

    def is_unspent(self, txid: str, index: int) -> bool:
        """Whether the output is unspent, counting spends still in the mempool."""


class SpendingClient(Protocol):
    """The Wasabi client calls a postmix spend needs."""

    name: str

    def stop_coinjoin(self) -> object:
        """Stop mixing so no coin is registered in a running round."""

    def check_mixed_coins(
        self,
        value: int | None = None,
        min_anon_score: float | None = None,
        unspent: Callable[[str, int], bool] | None = None,
    ) -> None:
        """Raise when the wallet's mixed coins cannot cover ``value`` yet."""

    def send_mixed_coins(
        self,
        destination: str,
        value: int | None = None,
        min_anon_score: float | None = None,
        unspent: Callable[[str, int], bool] | None = None,
        coin_selection: str = "anon_score",
    ) -> dict[str, object]:
        """Pay mixed coins to ``destination`` without change and describe the transaction."""


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
    coin_selection: str = "anon_score"
    status: str = "not_due"
    attempts: int = 0
    last_error: str | None = None
    next_attempt_at: float = 0.0
    sent: dict[str, object] = field(default_factory=dict)

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
            coin_selection=config.coin_selection,
        )

    def due(self, current_block: int, current_round: int) -> bool:
        return (
            self.status != "sent"
            and self.delay_blocks <= current_block
            and self.delay_rounds <= current_round
            and self.next_attempt_at <= time.time()
        )

    def mark_failed(self, error: Exception) -> None:
        self.status = "failed"
        self.last_error = str(error)
        self.next_attempt_at = time.time() + POSTMIX_RETRY_SECONDS

    def mark_sent(self, sent: dict[str, object]) -> None:
        self.status = "sent"
        self.last_error = None
        self.sent = sent

    def record(self) -> dict[str, object]:
        """The stored form: schedule and outcome in one flat object."""
        record = asdict(self)
        del record["next_attempt_at"], record["sent"]
        return record | self.sent


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

    def update(self, node: FundingNode, current_block: int, current_round: int) -> None:
        """Send every due postmix spend; a failed one is retried after a pause."""
        for spend in self.spends:
            if spend.due(current_block, current_round):
                self._send(spend, node, current_block, current_round)

    def _send(self, spend: PostmixSpend, node: FundingNode, current_block: int, current_round: int) -> None:
        """Attempt one spend and record its outcome."""
        client = self.clients[spend.wallet_index]
        spend.attempts += 1
        try:
            sent = self._pay_out(client, spend, node)
        except Exception as error:  # pylint: disable=broad-exception-caught
            spend.mark_failed(error)
            print(f"- postmix spend of {client.name} failed (attempt {spend.attempts}): {error}")
            return
        spend.mark_sent(sent | {"round": current_round, "block": current_block})
        print(f"- {client.name} spent {sent['amount_sats']} sats of mixed coins in {sent['txid']}")

    @staticmethod
    def _pay_out(client: SpendingClient, spend: PostmixSpend, node: FundingNode) -> dict[str, object]:
        """Pay the spend's mixed coins to a fresh funding-wallet address."""
        value = None if spend.all else spend.value
        # Stopping cancels the wallet's round, so a wallet still short of mixed coins
        # would never mix more if every retry stopped it.
        # The node, unlike the wallet, already knows which coins a coinjoin spent.
        client.check_mixed_coins(value, spend.min_anon_score, node.is_unspent)
        # A coin registered in a running round cannot be spent safely.
        client.stop_coinjoin()
        destination = node.get_new_address()
        result = client.send_mixed_coins(
            destination, value, spend.min_anon_score, node.is_unspent, spend.coin_selection
        )
        return result | {"destination": destination}

    def store(self, data_path: str) -> None:
        """Write the schedule with the outcome of each spend."""
        records = [spend.record() for spend in self.spends]
        with open(os.path.join(data_path, POSTMIX_SPENDS_FILE), "w", encoding="utf-8") as f:
            json.dump({"schema_version": POSTMIX_SPENDS_SCHEMA_VERSION, "spends": records}, f, indent=2)
        print(f"- stored {len(records)} postmix spends")
