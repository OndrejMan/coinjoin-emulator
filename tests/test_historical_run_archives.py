"""Black-box regression checks for preserved CoinJoin emulator run archives.

The emulator is intentionally nondeterministic, so a fresh run cannot be
compared byte-for-byte with a historical run.  These tests instead validate
the public archive contract: a scenario, a contiguous exported blockchain,
and one complete set of wallet artifacts for every configured wallet.

Set ``TESTING_DATA_DIR`` to run the checks against another archive collection.
The repository-level ``testing_data`` directory is used by default.
"""

import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from manager.engine.configuration import ScenarioConfig

DEFAULT_TESTING_DATA_DIR = Path(__file__).resolve().parents[2] / "testing_data"
WALLET_ARTIFACTS = ("coins.json", "unspent_coins.json", "keys.json")


def _testing_data_dir() -> Path:
    return Path(os.environ.get("TESTING_DATA_DIR", DEFAULT_TESTING_DATA_DIR))


def _archive_names(archive: ZipFile) -> list[str]:
    return [name for name in archive.namelist() if not name.endswith("/")]


def _archive_root(names: list[str]) -> str:
    roots = {Path(name).parts[0] for name in names}
    assert len(roots) == 1, f"expected one archive root, found {sorted(roots)}"
    return roots.pop()


def _load_json(archive: ZipFile, name: str) -> object:
    return json.loads(archive.read(name))


def _block_names(names: list[str], root: str) -> dict[int, str]:
    block_prefix = f"{root}/data/btc-node/block_"
    return {
        int(name.removeprefix(block_prefix).removesuffix(".json")): name
        for name in names
        if name.startswith(block_prefix) and name.endswith(".json")
    }


def _client_paths(names: list[str], root: str) -> set[Path]:
    client_prefix = f"{root}/data/wasabi-client-"
    return {
        Path(name).parent
        for name in names
        if name.startswith(client_prefix) and Path(name).name in WALLET_ARTIFACTS
    }


def _require_archives() -> list[Path]:
    archives = sorted(_testing_data_dir().glob("*.zip"))
    if not archives:
        pytest.skip(f"no historical emulator archives found in {_testing_data_dir()}")
    return archives


def test_historical_run_archives_follow_the_emulator_artifact_contract(tmp_path: Path) -> None:
    """Validate external emulator output without rerunning the emulator."""
    for archive_path in _require_archives():
        with ZipFile(archive_path) as archive:
            names = _archive_names(archive)
            root = _archive_root(names)
            scenario_name = f"{root}/scenario.json"
            assert scenario_name in names, f"{archive_path.name}: missing scenario.json"

            scenario_path = tmp_path / f"{archive_path.stem}-scenario.json"
            scenario_path.write_bytes(archive.read(scenario_name))
            scenario = ScenarioConfig.from_json_config(scenario_path)
            assert root.endswith(f"_{scenario.name}"), (
                f"{archive_path.name}: archive root does not end with the scenario name"
            )
            assert scenario.wallets, f"{archive_path.name}: scenario has no wallets"

            blocks = _block_names(names, root)
            assert blocks, f"{archive_path.name}: no exported block JSON files"
            assert sorted(blocks) == list(range(len(blocks))), f"{archive_path.name}: block heights are not contiguous"

            previous_hash: str | None = None
            for height, block_name in sorted(blocks.items()):
                block = _load_json(archive, block_name)
                assert isinstance(block, dict), f"{archive_path.name}: block {height} is not an object"
                assert block.get("height") == height, f"{archive_path.name}: block {height} has the wrong height"
                assert isinstance(block.get("hash"), str) and block["hash"], f"{archive_path.name}: invalid block hash"
                assert isinstance(block.get("tx"), list) and block["tx"], (
                    f"{archive_path.name}: block {height} has no tx list"
                )
                if previous_hash is not None:
                    assert block.get("previousblockhash") == previous_hash, (
                        f"{archive_path.name}: block {height} does not link to its predecessor"
                    )
                previous_hash = block["hash"]

            clients = _client_paths(names, root)
            assert len(clients) == len(scenario.wallets), (
                f"{archive_path.name}: expected {len(scenario.wallets)} wallet outputs, found {len(clients)}"
            )
            for client_path in clients:
                for artifact in WALLET_ARTIFACTS:
                    artifact_name = f"{client_path}/{artifact}"
                    assert artifact_name in names, f"{archive_path.name}: missing {artifact_name}"
                    _load_json(archive, artifact_name)


def test_historical_run_archives_have_a_consistent_transaction_and_wallet_view() -> None:
    """Validate transaction references and wallet snapshots from external output."""
    for archive_path in _require_archives():
        with ZipFile(archive_path) as archive:
            names = _archive_names(archive)
            root = _archive_root(names)
            blocks = _block_names(names, root)
            outputs: dict[tuple[str, int], dict[str, object]] = {}
            seen_txids: set[str] = set()
            spent_outpoints: set[tuple[str, int]] = set()

            for height, block_name in sorted(blocks.items()):
                block = _load_json(archive, block_name)
                assert isinstance(block, dict)
                transactions = block["tx"]
                assert isinstance(transactions, list)
                for transaction in transactions:
                    assert isinstance(transaction, dict), f"{archive_path.name}: invalid transaction in block {height}"
                    txid = transaction.get("txid")
                    assert isinstance(txid, str) and len(txid) == 64, f"{archive_path.name}: invalid transaction id"
                    assert txid not in seen_txids, f"{archive_path.name}: transaction {txid} appears more than once"
                    seen_txids.add(txid)

                    inputs = transaction.get("vin")
                    assert isinstance(inputs, list), f"{archive_path.name}: transaction {txid} has no input list"
                    for tx_input in inputs:
                        assert isinstance(tx_input, dict), f"{archive_path.name}: malformed input in {txid}"
                        if "coinbase" in tx_input:
                            continue
                        outpoint = (tx_input.get("txid"), tx_input.get("vout"))
                        assert outpoint in outputs, f"{archive_path.name}: {txid} spends an unknown output"
                        assert outpoint not in spent_outpoints, f"{archive_path.name}: output {outpoint} is spent twice"
                        spent_outpoints.add(outpoint)

                    transaction_outputs = transaction.get("vout")
                    assert isinstance(transaction_outputs, list), (
                        f"{archive_path.name}: transaction {txid} has no output list"
                    )
                    for index, output in enumerate(transaction_outputs):
                        assert isinstance(output, dict), f"{archive_path.name}: malformed output in {txid}"
                        outputs[(txid, index)] = output

            for client_path in _client_paths(names, root):
                coins = _load_json(archive, f"{client_path}/coins.json")
                unspent_coins = _load_json(archive, f"{client_path}/unspent_coins.json")
                keys = _load_json(archive, f"{client_path}/keys.json")
                assert isinstance(coins, list) and isinstance(unspent_coins, list) and isinstance(keys, list)

                keys_by_path = {
                    key.get("fullKeyPath"): key
                    for key in keys
                    if isinstance(key, dict) and isinstance(key.get("fullKeyPath"), str)
                }
                coin_outpoints: set[tuple[str, int]] = set()
                for coin in coins:
                    assert isinstance(coin, dict), f"{archive_path.name}: malformed wallet coin"
                    txid = coin.get("txid")
                    coin_index = coin.get("index")
                    assert isinstance(txid, str) and isinstance(coin_index, int), (
                        f"{archive_path.name}: wallet coin has an invalid outpoint"
                    )
                    outpoint = (txid, coin_index)
                    assert outpoint not in coin_outpoints, f"{archive_path.name}: duplicate wallet coin {outpoint}"
                    coin_outpoints.add(outpoint)
                    key = keys_by_path.get(coin.get("keyPath"))
                    assert key is not None, f"{archive_path.name}: wallet coin has an unknown key path"
                    assert coin.get("address") == key.get("address"), (
                        f"{archive_path.name}: wallet coin address does not match its key"
                    )

                for coin in unspent_coins:
                    assert isinstance(coin, dict), f"{archive_path.name}: malformed unspent wallet coin"
                    outpoint = (coin.get("txid"), coin.get("index"))
                    assert outpoint in coin_outpoints, f"{archive_path.name}: unspent coin is absent from coins.json"
