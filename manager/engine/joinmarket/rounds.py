"""Per-tick client updates and the resource watchdog."""

import asyncio
import random
from collections.abc import Coroutine
from typing import TYPE_CHECKING, cast

from manager.driver import Driver
from manager.engine.base.protocols import EmulatorClient
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer
from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import OrderbookWatchClient


class JoinMarketRoundsMixin:
    """Drives the clients one block at a time, synchronously or concurrently."""

    driver: Driver
    clients: list[EmulatorClient]
    obwatch_client: OrderbookWatchClient | None
    _obwatch_missing_logged: bool = False
    async_updates: bool
    last_resource_check: int
    current_block: int
    current_round: int

    if TYPE_CHECKING:
        def collect_round_events(self) -> list[dict[str, object]]: ...

    def _note_missing_obwatch(self) -> None:
        """Report once that the orderbook watcher is unavailable for this run.

        Startup failures are tolerated, so a missing watcher is a valid state.
        Reporting it every round would drown the log, so this is said once.
        """
        if self._obwatch_missing_logged:
            return
        self._obwatch_missing_logged = True
        print("- orderbook watcher is not running, skipping its updates for this run")

    def update_coinjoins_joinmarket(self) -> None:
        for emulator_client in self.clients:
            client = cast(JoinMarketClientServer, emulator_client)
            try:
                # Check if client just reached its limit
                was_active = not client.is_paused(self.current_block)
                delta = client.update(self.current_block, self.current_round)
                now_paused = client.is_paused(self.current_block)

                # Log when a client reaches its coinjoin limit
                if was_active and now_paused and hasattr(client, 'max_coinjoins') and client.max_coinjoins > 0:
                    if hasattr(client, 'completed_coinjoins') and client.completed_coinjoins >= client.max_coinjoins:
                        print(f"✓ {client.name} reached max coinjoins limit ({client.max_coinjoins})")

                # Apply any change in round count; alternatively, have the client trigger an event.
                self.current_round += delta
            except Exception as e:
                print(f"- could not update {client.name} ({e})")

        if self.obwatch_client is not None:
            try:
                self.obwatch_client.update(self.current_block, self.current_round)
            except Exception as e:
                print(f"- could not update obwatch client ({e})")
        else:
            self._note_missing_obwatch()

    async def update_coinjoins_joinmarket_async(self) -> None:
        """
        Async version: Update all clients in parallel using asyncio.gather()
        Adds jitter between task creation to prevent synchronized RPC storms
        """
        # Create tasks for all client updates with jitter to desynchronize RPC calls
        client_tasks: list[Coroutine[object, object, int]] = []
        for emulator_client in self.clients:
            task = self._update_client_async(cast(JoinMarketClientServer, emulator_client))
            client_tasks.append(task)
            # Add jitter between task creations to desynchronize Bitcoin Core RPC calls
            jitter = random.uniform(0.01, 0.05)  # 10-50ms jitter
            await asyncio.sleep(jitter)

        # Add orderbook watcher client task if it exists
        if self.obwatch_client:
            client_tasks.append(self._update_obwatch_async(self.obwatch_client))
        else:
            self._note_missing_obwatch()

        # Run all updates concurrently
        results = await asyncio.gather(*client_tasks, return_exceptions=True)
        
        # Process results and update round count
        for i, result in enumerate(results[:-1] if self.obwatch_client else results):
            if isinstance(result, Exception):
                client_name = self.clients[i].name if i < len(self.clients) else "unknown"
                print(f"- could not update {client_name} ({result})")
            elif isinstance(result, int):
                # Apply any change in round count
                self.current_round += result

    async def _update_client_async(self, client: JoinMarketClientServer) -> int:
        """Helper to update a single client asynchronously"""
        try:
            delta = await client.update_async(self.current_block, self.current_round)
            return delta
        except Exception as e:
            print(f"- could not update {client.name} ({e})")
            return 0

    async def _update_obwatch_async(self, obwatch_client: JoinMarketClientServer) -> int:
        """Helper to update orderbook watcher client asynchronously"""
        try:
            return await obwatch_client.update_async(self.current_block, self.current_round)
        except Exception as e:
            print(f"- could not update obwatch client ({e})")
            return 0

    def check_client_resources(self) -> None:
        """
        Check resource usage for a sample of client pods.
        Logs memory usage and alerts if pods are near limits.
        """
        # Sample 5 random clients to avoid overhead
        sample_size = min(5, len(self.clients))
        sample_clients = random.sample(self.clients, sample_size) if self.clients else []

        high_usage_count = 0
        for client in sample_clients:
            stats = getattr(self.driver, "get_pod_resource_usage", None)
            stats = stats(client.name) if stats is not None else None
            if stats:
                mem_mb = stats['memory_mb']
                mem_limit = stats['memory_limit_mb']
                mem_pct = stats['memory_percent']

                # Log if usage is over 80%
                if mem_pct > 80:
                    print(f"[RESOURCE WARNING] {client.name}: {mem_mb:.1f}/{mem_limit}MB ({mem_pct:.1f}%)")
                    high_usage_count += 1
                elif mem_pct > 60:
                    print(f"[RESOURCE] {client.name}: {mem_mb:.1f}/{mem_limit}MB ({mem_pct:.1f}%)")

        if high_usage_count > 0:
            print(f"[RESOURCE] {high_usage_count}/{sample_size} sampled pods using >80% memory")
