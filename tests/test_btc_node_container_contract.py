"""Static contracts for the Bitcoin Core container entrypoints."""

from pathlib import Path

CONTAINER_DIR = Path(__file__).resolve().parents[1] / "containers" / "btc-node"


def test_miner_rpc_calls_request_responses() -> None:
    miner = (CONTAINER_DIR / "mine.sh").read_text(encoding="utf-8")

    assert '"jsonrpc": "2.0"' not in miner
    assert '"jsonrpc": "1.0"' in miner
