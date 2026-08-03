"""The producer-label manifest that records how complete the captured labels are."""

import hashlib
import json
import os

PRODUCER_LABEL_MANIFEST = "coinjoin_label_manifest.json"
PRODUCER_LABEL_MANIFEST_SCHEMA_VERSION = "1.0"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_producer_label_manifest(data_path: str, evidence: dict[str, object] | None) -> None:
    """Atomically record whether producer-owned CoinJoin labels were captured completely."""
    evidence = evidence or {
        "engine": "unknown",
        "complete": False,
        "reason": "engine did not provide producer-label evidence",
        "sources": [],
    }
    raw_sources = evidence.get("sources")
    source_names = raw_sources if isinstance(raw_sources, list) else []
    data_root = os.path.realpath(data_path)
    source_records = []
    complete = evidence.get("complete") is True
    reason = evidence.get("reason")

    for source_name in source_names:
        if not isinstance(source_name, str) or not source_name:
            complete = False
            reason = reason or "producer-label source path is invalid"
            continue
        source_path = os.path.realpath(os.path.join(data_root, source_name))
        if os.path.commonpath((data_root, source_path)) != data_root or not os.path.isfile(source_path):
            complete = False
            reason = reason or f"producer-label source is missing: {source_name}"
            continue
        source_records.append({
            "path": os.path.relpath(source_path, data_root).replace(os.sep, "/"),
            "size_bytes": os.path.getsize(source_path),
            "sha256": _sha256_file(source_path),
        })

    if complete and not source_records:
        complete = False
        reason = reason or "producer-label capture produced no source files"

    manifest = {
        "schema_version": PRODUCER_LABEL_MANIFEST_SCHEMA_VERSION,
        "engine": evidence.get("engine"),
        "complete": complete,
        "reason": None if complete else str(reason or "producer-label capture was incomplete"),
        "positive_rule": evidence.get("positive_rule"),
        "positive_count": evidence.get("positive_count"),
        "sources": source_records,
    }
    manifest_path = os.path.join(data_path, PRODUCER_LABEL_MANIFEST)
    temporary_path = f"{manifest_path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary_path, manifest_path)
