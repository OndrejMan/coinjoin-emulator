"""Wallet client start-up, ordered by the roles the scenario declares."""

import multiprocessing
import multiprocessing.pool
from time import sleep
from typing import TYPE_CHECKING

from manager.engine.base.protocols import EmulatorClient
from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.exceptions import CoinjoinEmulatorError


def _has_fidelity_bond(wallet: WalletConfig) -> bool:
    """True when the wallet asks for a fidelity bond (typed scenario model)."""
    bond = (wallet.joinmarket.fidelity_bond if wallet.joinmarket else None) or {}
    return bool(bond.get("enabled", False))


class EngineClientsMixin:
    """Starts the scenario wallets and keeps the engine client list in order."""

    clients: list[EmulatorClient]
    scenario: ScenarioConfig

    if TYPE_CHECKING:
        # pylint: disable=unused-argument  # these are stub signatures
        def start_client(self, idx: int, wallet: WalletConfig | None = None) -> EmulatorClient | None: ...
        def stop_client(self, idx: int) -> None: ...

    def _start_classified_wallets(
        self,
        pool: multiprocessing.pool.ThreadPool,
        wallet_list: list[tuple[int, WalletConfig]],
        fb_batch_size: int = 5,
        fb_batch_delay: int = 15,
    ) -> dict[int, EmulatorClient | None]:
        """
        Start a list of (idx, wallet) tuples with smart batching:
        - Regular wallets: all in parallel
        - FB wallets: in small batches to avoid Bitcoin RPC overload

        Returns dict: {idx: client} (client is None if startup failed)
        """
        # Classify into regular and FB wallets
        regular_wallets = []
        fb_wallets = []

        for idx, wallet in wallet_list:
            if _has_fidelity_bond(wallet):
                fb_wallets.append((idx, wallet))
            else:
                regular_wallets.append((idx, wallet))

        results: dict[int, EmulatorClient | None] = {}

        # Start regular wallets in parallel (fast)
        if regular_wallets:
            regular_clients = pool.starmap(self.start_client, regular_wallets)
            for (idx, _), client in zip(regular_wallets, regular_clients):
                results[idx] = client

        # Start FB wallets in batches (slow, avoid RPC overload)
        if fb_wallets:
            for batch_start in range(0, len(fb_wallets), fb_batch_size):
                batch_end = min(batch_start + fb_batch_size, len(fb_wallets))
                batch = fb_wallets[batch_start:batch_end]

                batch_clients = pool.starmap(self.start_client, batch)
                for (idx, _), client in zip(batch, batch_clients):
                    results[idx] = client

                # Wait before next batch (unless last batch)
                if batch_end < len(fb_wallets) and fb_batch_delay > 0:
                    print(f"  - waiting {fb_batch_delay}s before next batch")
                    sleep(fb_batch_delay)

        return results

    def start_clients(self, wallets: list[WalletConfig]) -> None:
        print("Starting clients")

        fb_batch_size = 5   # FB wallets per batch
        fb_batch_delay = 15  # Seconds between FB batches

        # Build initial wallet list with indices
        wallet_list = list(enumerate(wallets, start=len(self.clients)))

        # Count wallet types for logging
        fb_count = sum(1 for _, w in wallet_list if _has_fidelity_bond(w))
        print(f"- {len(wallet_list) - fb_count} regular wallets, {fb_count} fidelity bond wallets")

        with multiprocessing.pool.ThreadPool() as pool:
            new_clients: list[EmulatorClient | None] = [None] * len(wallets)

            # Initial startup
            print(f"- starting {len(wallet_list)} wallets")
            if fb_count > 0:
                print(f"  - FB wallets will be started in batches of {fb_batch_size}")

            startup_results = self._start_classified_wallets(pool, wallet_list, fb_batch_size, fb_batch_delay)
            for idx, client in startup_results.items():
                new_clients[idx - len(self.clients)] = client

            # Retry logic (uses same classification/batching)
            for _ in range(3):
                failed_indices = [
                    idx for idx, client in enumerate(new_clients, start=len(self.clients))
                    if client is None
                ]

                if not failed_indices:
                    break

                print(f"- failed to start {len(failed_indices)} clients; retrying ...")

                # Stop and rebuild wallet list for failed clients
                for idx in failed_indices:
                    self.stop_client(idx)
                sleep(60)

                retry_wallet_list = [(idx, wallets[idx - len(self.clients)]) for idx in failed_indices]

                # Retry with same smart batching
                retry_results = self._start_classified_wallets(pool, retry_wallet_list, fb_batch_size, fb_batch_delay)
                for idx, client in retry_results.items():
                    new_clients[idx - len(self.clients)] = client
            failed_count = sum(client is None for client in new_clients)
            if failed_count:
                raise RuntimeError(
                    f"Failed to start {failed_count} clients after retries; aborting experiment"
                )

        self.clients.extend(client for client in new_clients if client is not None)

    def validate_clients(self) -> None:
        """Require every declared wallet to answer before funding begins."""
        expected = len(self.scenario.wallets)
        actual = len(self.clients)
        if actual != expected:
            raise RuntimeError(f"Expected {expected} clients, but only {actual} started")

        def healthcheck(client: EmulatorClient) -> tuple[str, bool, str | None]:
            try:
                # Startup already waited for and, for JoinMarket, created the
                # wallet.  Calling wait_wallet() again is not a read-only
                # health check there: it calls /wallet/create again and can
                # loop on "Wallet already unlocked" until the timeout.
                client.get_balance()
            except (CoinjoinEmulatorError, OSError, TypeError, ValueError) as error:
                return client.name, False, str(error)
            return client.name, True, None

        with multiprocessing.pool.ThreadPool() as pool:
            results = pool.map(healthcheck, self.clients)
        failed = [
            f"{name} ({detail or 'RPC health-check timed out'})"
            for name, healthy, detail in results
            if not healthy
        ]
        if failed:
            raise RuntimeError(
                "Client RPC health-check failed before funding: " + ", ".join(failed)
            )
