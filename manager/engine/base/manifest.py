"""The producer-label manifest that records how complete the captured labels are."""

import hashlib
import json
import os
from typing import NotRequired, TypedDict

PRODUCER_LABEL_MANIFEST = "coinjoin_label_manifest.json"
PRODUCER_LABEL_MANIFEST_SCHEMA_VERSION = "1.0"
BYTES_IN_MEGABYTE = 1024 * 1024


class ProducerLabelEvidence(TypedDict):
    """Engine-owned records used to establish the producer-label contract."""

    engine: str
    complete: bool
    sources: list[str]
    reason: NotRequired[str | None]
    positive_rule: NotRequired[str]
    positive_count: NotRequired[int]


class ManifestSource(TypedDict):
    """One source file whose contents contribute producer-label evidence."""

    path: str
    size_bytes: int
    sha256: str


class ProducerLabelManifest(TypedDict):
    """Serialized producer-label manifest contract."""

    schema_version: str
    engine: str
    complete: bool
    reason: str | None
    positive_rule: str | None
    positive_count: int | None
    sources: list[ManifestSource]


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(BYTES_IN_MEGABYTE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_producer_label_manifest(
    data_path: str,
    evidence: ProducerLabelEvidence | None,
) -> None:
    """Atomically record whether producer-owned CoinJoin labels were captured completely."""
    if evidence is None:
        evidence = {
            "engine": "unknown",
            "complete": False,
            "sources": [],
        }
    source_names = evidence["sources"]
    data_root = os.path.realpath(data_path)
    source_records: list[ManifestSource] = []
    complete = evidence["complete"]
    reason = evidence.get("reason")

    for source_name in source_names:
        if not source_name:
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

    manifest: ProducerLabelManifest = {
        "schema_version": PRODUCER_LABEL_MANIFEST_SCHEMA_VERSION,
        "engine": evidence["engine"],
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
