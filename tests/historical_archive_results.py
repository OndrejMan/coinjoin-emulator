"""Compare legacy Wasabi replay outcomes without comparing random transaction IDs."""

import json
import math
import re
from pathlib import Path
from zipfile import ZipFile

COMPARABLE_METRICS = (
    "broadcast_coinjoins",
    "mined_coinjoins",
    "coinjoin_inputs",
    "coinjoin_outputs",
)


def archive_results(path: Path) -> dict:
    with ZipFile(path) as archive:
        names = archive.namelist()
        stores = [name for name in names if name.endswith("/WabiSabi/CoinJoinIdStore.txt")]
        assert len(stores) == 1, f"{path}: expected one legacy Wasabi CoinJoinIdStore.txt"
        txids = {line.strip().lower() for line in archive.read(stores[0]).decode().splitlines() if line.strip()}
        assert all(re.fullmatch(r"[0-9a-f]{64}", txid) for txid in txids), f"{path}: invalid CoinJoin ID"
        blocks = [
            json.loads(archive.read(name)) for name in names if re.search(r"/data/btc-node/block_\d+\.json$", name)
        ]
        assert blocks, f"{path}: no blocks"
        coinjoins = [tx for block in blocks for tx in block["tx"] if tx["txid"].lower() in txids]
        wallets = sorted(
            {
                name.split("/data/")[1].split("/")[0]
                for name in names
                if re.search(r"/data/wasabi-client-\d+/coins\.json$", name)
            }
        )
        assert wallets, f"{path}: no wallet exports"
        return {
            "wallets": wallets,
            "broadcast_coinjoins": len(txids),
            "mined_coinjoins": len(coinjoins),
            "coinjoin_inputs": sum(len(tx["vin"]) for tx in coinjoins),
            "coinjoin_outputs": sum(len(tx["vout"]) for tx in coinjoins),
            # Diagnostic only: startup/settlement mining changed since these archives.
            "exported_blocks": len(blocks),
        }


def compare_results(reference: dict, replay: dict, relative_tolerance: float) -> dict:
    if not math.isfinite(relative_tolerance) or not 0 <= relative_tolerance < 1:
        raise ValueError("relative tolerance must be finite and in [0, 1)")
    differences = []
    if reference["wallets"] != replay["wallets"]:
        differences.append("wallet identities differ")
    metrics = {}
    for name in COMPARABLE_METRICS:
        expected, actual = reference[name], replay[name]
        allowed = expected * relative_tolerance
        passed = abs(actual - expected) <= allowed
        metrics[name] = {
            "reference": expected,
            "replay": actual,
            "delta": actual - expected,
            "allowed_delta": allowed,
            "passed": passed,
        }
        if not passed:
            differences.append(f"{name}: {actual}, expected {expected} +/- {allowed:g}")
    return {
        "relative_tolerance": relative_tolerance,
        "metrics": metrics,
        "reference": reference,
        "replay": replay,
        "differences": differences,
    }
