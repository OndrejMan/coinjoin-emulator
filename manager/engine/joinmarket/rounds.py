from typing import TYPE_CHECKING, cast

import requests

from manager import log_output as log

from ...btc_node import BtcNode
from ...exceptions import CoinjoinEmulatorError
from ..configuration import ScenarioConfig
from ..engine_base import EmulatorClient
from .constants import (
    JOINMARKET_COINJOIN_AMOUNT_SATS,
    JOINMARKET_COUNTERPARTIES,
    JOINMARKET_MAKER_MIN_SIZE_SATS,
    JOINMARKET_ROUND_TIMEOUT_BLOCKS,
    JOINMARKET_TAKER_MAX_ATTEMPTS,
    JOINMARKET_TAKER_RETRY_COOLDOWN_BLOCKS,
)


class JoinMarketRoundMixin:
    node: BtcNode | None
    clients: list[EmulatorClient]
    joinmarket_round_events: list[dict[str, object]]
    scenario: ScenarioConfig
    current_block: int
    current_round: int

    if TYPE_CHECKING:
        def confirm_started_rounds(self) -> int: ...

    def _active_round_for_taker(self, taker_name: str) -> bool:
        return any(
            event.get("status") == "started" and event.get("taker") == taker_name
            for event in self.joinmarket_round_events
        )

    def _has_active_round(self) -> bool:
        return any(
            event.get("status") == "started"
            for event in self.joinmarket_round_events
        )

    def _started_round_count(self) -> int:
        return len([
            event for event in self.joinmarket_round_events
            if event.get("status") in ("started", "confirmed", "stopped")
        ])

    def _next_round_id(self) -> int:
        round_ids = [
            int(cast(int, event.get("round_id") or 0))
            for event in self.joinmarket_round_events
        ]
        return max(round_ids, default=0) + 1

    def _event_target_round(self, event: dict[str, object]) -> int:
        return int(cast(int, event.get("target_round") or self.current_round + 1))

    def _taker_attempt_count(self, taker_name: str, target_round: int) -> int:
        return len([
            event for event in self.joinmarket_round_events
            if event.get("taker") == taker_name
            and self._event_target_round(event) == target_round
        ])

    def _round_retry_after_block(self, target_round: int) -> int:
        retry_blocks = [
            int(cast(int, event.get("retry_after_block") or 0))
            for event in self.joinmarket_round_events
            if event.get("status") == "failed"
            and self._event_target_round(event) == target_round
        ]
        return max(retry_blocks, default=0)

    def _eligible_takers(self, target_round: int) -> list[EmulatorClient]:
        takers = [
            client for client in self.clients
            if client.type == "taker"
            and not client.coinjoin_in_process
            and client.delay[0] <= self.current_block
            and not self._active_round_for_taker(client.name)
        ]
        return sorted(
            takers,
            key=lambda client: (
                self._taker_attempt_count(client.name, target_round),
                client.name,
            ),
        )

    def _restart_round_makers(self, event: dict[str, object]) -> None:
        maker_names = {
            str(name)
            for name in cast(list[object], event.get("candidate_makers") or [])
        }
        if not maker_names:
            return
        for client in self.clients:
            if client.name not in maker_names or not client.maker_running:
                continue
            try:
                client.stop_maker()
            except (
                requests.exceptions.RequestException,
                CoinjoinEmulatorError,
                RuntimeError,
                OSError,
                TimeoutError,
                KeyError,
                TypeError,
                ValueError,
            ) as e:
                event.setdefault("maker_restart_errors", [])
                cast(list[str], event["maker_restart_errors"]).append(f"{client.name}: {e}")
                log.warning(f"- could not stop JoinMarket maker {client.name} before retry: {e}")
            finally:
                client.maker_running = False

    def _mark_round_failed(self, event: dict[str, object], reason: str) -> None:
        event["status"] = "failed"
        event["stop_block"] = self.current_block
        event["failure_reason"] = reason
        event["retry_after_block"] = self.current_block + JOINMARKET_TAKER_RETRY_COOLDOWN_BLOCKS
        taker_name = event.get("taker")
        for client in self.clients:
            if client.name == taker_name:
                try:
                    client.stop_coinjoin()
                except (
                    requests.exceptions.RequestException,
                    CoinjoinEmulatorError,
                    RuntimeError,
                    OSError,
                    TimeoutError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as e:
                    event["stop_error"] = str(e)
                    log.warning(f"- could not stop failed JoinMarket round for {taker_name}: {e}")
                finally:
                    client.coinjoin_in_process = False
                break
        self._restart_round_makers(event)
        log.warning(f"- JoinMarket round for {taker_name} failed: {reason}")

    def _expire_stalled_rounds(self) -> None:
        for event in self.joinmarket_round_events:
            if event.get("status") != "started":
                continue
            age = self.current_block - int(cast(int, event.get("start_block") or 0))
            if age <= JOINMARKET_ROUND_TIMEOUT_BLOCKS:
                continue
            self._mark_round_failed(
                event,
                "did not produce a mined destination output within "
                f"{JOINMARKET_ROUND_TIMEOUT_BLOCKS} blocks",
            )

    def _fail_inactive_started_rounds(self) -> None:
        active_takers = {
            client.name
            for client in self.clients
            if client.type == "taker" and client.coinjoin_in_process
        }
        for event in self.joinmarket_round_events:
            if event.get("status") != "started":
                continue
            taker_name = str(event.get("taker") or "")
            if taker_name in active_takers:
                continue
            start_block = int(cast(int, event.get("start_block") or 0))
            if self.current_block <= start_block:
                continue
            self._mark_round_failed(
                event,
                "taker service stopped before a mined destination output was found",
            )

    def _client_confirmed_balance(self, client: EmulatorClient) -> int:
        try:
            return client.get_balance()
        except (CoinjoinEmulatorError, RuntimeError, OSError, KeyError, TypeError, ValueError) as e:
            log.warning(f"- waiting for {client.name} wallet balance ({e})")
            return 0

    def _client_has_confirmed_balance(
        self, client: EmulatorClient, required_sats: int, role: str
    ) -> bool:
        balance = self._client_confirmed_balance(client)
        if balance < required_sats:
            log.info(
                f"- waiting for JoinMarket {role} {client.name} balance "
                f"({balance}/{required_sats} sats)"
            )
            return False
        return True

    def update_coinjoins_joinmarket(self) -> None:
        self.confirm_started_rounds()
        self._expire_stalled_rounds()

        for client in self.clients:
            try:
                client.get_status()
            except (requests.exceptions.RequestException, CoinjoinEmulatorError, RuntimeError, OSError,
                    KeyError, TypeError, ValueError) as e:
                log.warning(f"- skipping JoinMarket status update for {client.name}: {e}")
        self._fail_inactive_started_rounds()

        for client in self.clients:
            if client.type == "maker" and not client.maker_running and client.delay[0] <= self.current_block:
                if not self._client_has_confirmed_balance(client, JOINMARKET_MAKER_MIN_SIZE_SATS, "maker"):
                    continue
                log.info(f"Starting maker {client.name}")
                try:
                    client.start_maker(0, 5000, 0.00004, "sw0reloffer", JOINMARKET_MAKER_MIN_SIZE_SATS)
                except (requests.exceptions.RequestException, CoinjoinEmulatorError, RuntimeError, OSError,
                        KeyError, TypeError, ValueError) as e:
                    log.warning(f"- failed to start JoinMarket maker {client.name}: {e}")
                    continue
                try:
                    client.get_status()
                except (requests.exceptions.RequestException, CoinjoinEmulatorError, RuntimeError, OSError,
                        KeyError, TypeError, ValueError):
                    pass

        running_makers = [
            maker for maker in self.clients
            if maker.type == "maker" and maker.maker_running
        ]
        if len(running_makers) < JOINMARKET_COUNTERPARTIES:
            log.info(
                f"- waiting for JoinMarket makers "
                f"({len(running_makers)}/{JOINMARKET_COUNTERPARTIES} running)"
            )
            return

        total_started_rounds = self._started_round_count()
        target_round = self.current_round + 1
        retry_after_block = self._round_retry_after_block(target_round)
        if retry_after_block > self.current_block:
            log.info(
                f"- waiting for JoinMarket retry cooldown "
                f"(block {self.current_block}/{retry_after_block})"
            )
            return

        can_start_more_rounds = self.scenario.rounds == 0 or total_started_rounds < self.scenario.rounds
        if not can_start_more_rounds or self._has_active_round():
            return

        for client in self._eligible_takers(target_round):
            attempt = self._taker_attempt_count(client.name, target_round) + 1
            if attempt > JOINMARKET_TAKER_MAX_ATTEMPTS:
                log.warning(
                    f"- skipping JoinMarket taker {client.name}; exhausted "
                    f"{JOINMARKET_TAKER_MAX_ATTEMPTS} attempt(s) for round {target_round}"
                )
                continue
            if (
                client.type == "taker"
                and not client.coinjoin_in_process
                and client.delay[0] <= self.current_block
                and not self._active_round_for_taker(client.name)
            ):
                if not self._client_has_confirmed_balance(client, JOINMARKET_COINJOIN_AMOUNT_SATS, "taker"):
                    continue
                try:
                    address = client.get_new_address()
                except (requests.exceptions.RequestException, CoinjoinEmulatorError, RuntimeError, OSError,
                        KeyError, TypeError, ValueError) as e:
                    log.warning(f"- failed to get JoinMarket destination address for {client.name}: {e}")
                    continue
                maker_names = [maker.name for maker in running_makers]
                try:
                    client.start_coinjoin(0, JOINMARKET_COINJOIN_AMOUNT_SATS, JOINMARKET_COUNTERPARTIES, address)
                except (requests.exceptions.RequestException, CoinjoinEmulatorError, RuntimeError, OSError,
                        KeyError, TypeError, ValueError) as e:
                    log.warning(f"- failed to start JoinMarket coinjoin for {client.name}: {e}")
                    continue
                client.coinjoin_in_process = True
                client.coinjoin_start = self.current_block
                round_id = self._next_round_id()
                total_started_rounds += 1
                self.joinmarket_round_events.append({
                    "round_id": round_id,
                    "target_round": target_round,
                    "attempt": attempt,
                    "engine": "joinmarket",
                    "status": "started",
                    "taker": client.name,
                    "candidate_makers": maker_names,
                    "counterparties": JOINMARKET_COUNTERPARTIES,
                    "amount_sats": JOINMARKET_COINJOIN_AMOUNT_SATS,
                    "mixdepth": 0,
                    "destination_address": address,
                    "start_block": self.current_block,
                    "start_chain_height": self.node.get_block_count() if self.node is not None else None,
                })
                log.info(f"Starting coinjoin {client.name}")
                break
