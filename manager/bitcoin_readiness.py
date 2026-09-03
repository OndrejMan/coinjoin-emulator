"""Readiness policy for the Bitcoin Core node used by emulator engines."""

from collections.abc import Mapping
from time import monotonic, sleep
from typing import Protocol

import requests

from .exceptions import RpcError

MINIMUM_READY_BLOCKS = 200
QUIET_SAMPLE_COUNT = 6
QUIET_SAMPLE_INTERVAL_SECONDS = 0.5


class ReadyBitcoinNode(Protocol):
    """The small BtcNode interface needed to decide whether startup may continue."""

    host: str
    port: int

    def get_block_count(self) -> int:
        ...

    def get_blockchain_info(self) -> Mapping[str, object]:
        ...

    def estimate_smart_fee(self) -> Mapping[str, object]:
        ...

    def ensure_funding_wallet_ready(self) -> None:
        ...


def wait_for_node_ready(node: ReadyBitcoinNode, timeout: float = 600) -> None:
    """Wait for synchronized chain, usable funding wallet, and finished fee history."""
    deadline = monotonic() + timeout
    _wait_for_synchronized_chain_and_wallet(node, deadline, timeout)

    # The miner keeps building fee history after the chain is mined. Wasabi
    # cannot start until estimatesmartfee returns a feerate.
    wait_for_fee_history(node, max(0.0, deadline - monotonic()))


def wait_for_fee_history(node: ReadyBitcoinNode, timeout: float = 300) -> None:
    """Wait for a fee estimate and a stable synchronized chain tip."""
    deadline = monotonic() + timeout
    _wait_for_smart_fee_estimate(node, deadline, timeout)
    _wait_for_quiet_chain_tip(node, deadline, timeout)


def _wait_for_synchronized_chain_and_wallet(node: ReadyBitcoinNode, deadline: float, timeout: float) -> None:
    last_state = "no successful RPC sample"
    while monotonic() < deadline:
        try:
            block_count = node.get_block_count()
            info = node.get_blockchain_info()
            last_state = _format_synchronization_state(block_count, info)
            if block_count > MINIMUM_READY_BLOCKS and _is_synchronized(info, block_count):
                node.ensure_funding_wallet_ready()
                return
        except (requests.exceptions.RequestException, RpcError) as error:
            last_state = f"RPC error: {error}"
        sleep(1)
    raise TimeoutError(f"btc-node RPC at {node.host}:{node.port} was not ready after {timeout}s ({last_state})")


def _wait_for_smart_fee_estimate(node: ReadyBitcoinNode, deadline: float, timeout: float) -> None:
    while monotonic() < deadline:
        try:
            if node.estimate_smart_fee().get("feerate") is not None:
                return
        except (requests.exceptions.RequestException, RpcError):
            pass
        sleep(1)
    raise TimeoutError(f"btc-node produced no smart fee estimate after {timeout:.0f}s")


def _wait_for_quiet_chain_tip(node: ReadyBitcoinNode, deadline: float, timeout: float) -> None:
    streak = 0
    quiet_height = None
    while monotonic() < deadline:
        try:
            info = node.get_blockchain_info()
            blocks = info.get("blocks")
            if not _is_synchronized(info, blocks):
                quiet_height = None
                streak = 0
            elif blocks == quiet_height:
                streak += 1
            else:
                quiet_height = blocks
                streak = 1
            if streak >= QUIET_SAMPLE_COUNT:
                return
        except (requests.exceptions.RequestException, RpcError):
            quiet_height = None
            streak = 0
        sleep(QUIET_SAMPLE_INTERVAL_SECONDS)
    raise TimeoutError(f"btc-node did not become quietly synchronized after {timeout:.0f}s")


def _is_synchronized(info: Mapping[str, object], block_count: object) -> bool:
    progress = info.get("verificationprogress")
    return (
        isinstance(block_count, int)
        and info.get("headers") == block_count
        and info.get("initialblockdownload") is False
        and isinstance(progress, (int, float))
        and progress >= 1.0
    )


def _format_synchronization_state(block_count: int, info: Mapping[str, object]) -> str:
    return (
        f"blocks={block_count} headers={info.get('headers')} "
        f"initialblockdownload={info.get('initialblockdownload')} "
        f"progress={info.get('verificationprogress')}"
    )
