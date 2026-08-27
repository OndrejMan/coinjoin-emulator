from pathlib import Path

MINE_SCRIPT = Path(__file__).parents[1] / "containers" / "btc-node" / "mine.sh"


def test_miner_routes_bitcoin_cli_to_regtest_rpc() -> None:
    script = MINE_SCRIPT.read_text(encoding="utf-8")

    assert "-regtest" in script
    assert "-rpcconnect=127.0.0.1" in script
    assert "-rpcport=18443" in script
    assert "-rpcwallet=wallet" in script

    direct_invocations = [
        line.strip()
        for line in script.splitlines()
        if "bitcoin-cli" in line and not line.lstrip().startswith("#")
    ]
    assert direct_invocations == ["bitcoin-cli \\"]
