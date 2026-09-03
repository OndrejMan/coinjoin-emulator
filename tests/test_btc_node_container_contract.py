"""Static contracts for the Bitcoin Core container entrypoints."""

from pathlib import Path

CONTAINER_DIR = Path(__file__).resolve().parents[1] / "containers" / "btc-node"


def test_miner_rpc_calls_request_responses() -> None:
    miner = (CONTAINER_DIR / "mine.sh").read_text(encoding="utf-8")

    assert '"jsonrpc": "2.0"' not in miner
    assert '"jsonrpc": "1.0"' in miner


def test_miner_readiness_wait_is_bounded() -> None:
    miner = (CONTAINER_DIR / "mine.sh").read_text(encoding="utf-8")

    assert "BITCOIND_READY_TIMEOUT_SECONDS=60" in miner
    assert "BITCOIND_READY_DEADLINE" in miner
    assert miner.count('if [ "$CURRENT_TIME" -ge "$BITCOIND_READY_DEADLINE" ]') == 1
    assert "Timed out waiting" in miner
    assert "curl --max-time 5" in miner


def test_miner_only_mines_missing_initial_blocks() -> None:
    miner = (CONTAINER_DIR / "mine.sh").read_text(encoding="utf-8")

    assert "BLOCKS_TO_MINE=$((INITIAL_BLOCK_COUNT - BLOCK_COUNT))" in miner
    assert '\\"params\\": [$BLOCKS_TO_MINE, \\"$ADDR\\"]' in miner


def test_entrypoint_forwards_bitcoind_arguments() -> None:
    entrypoint = (CONTAINER_DIR / "run.sh").read_text(encoding="utf-8")

    assert 'maxconnections=1024 "$@"' in entrypoint
