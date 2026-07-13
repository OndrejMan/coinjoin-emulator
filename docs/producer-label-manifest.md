# Producer label manifest (`data/coinjoin_label_manifest.json`)

Every stored run writes this manifest next to the other `data/` artifacts. It
is the machine-verifiable statement of whether the engine captured its own
CoinJoin label evidence completely. Downstream analyzers must not label
transactions from a run whose manifest is missing or does not verify.

The writer is `manager/engine/engine_base.py::write_producer_label_manifest`;
the pipeline-side verifier is
`coinjoin-pipeline/pipeline/exporters/emulator_data.py::verified_producer_label_sources`.
The consumer-facing semantics are documented in
`coinjoin-pipeline/docs/analysis-semantics.md`.

## Schema (version `1.0`)

```json
{
  "schema_version": "1.0",
  "engine": "joinmarket",
  "complete": true,
  "reason": null,
  "positive_rule": "exported transaction matches a reconciled JoinMarket round event",
  "sources": [
    {
      "path": "joinmarket_round_events.json",
      "size_bytes": 4213,
      "sha256": "…64 hex chars…"
    }
  ]
}
```

- `schema_version`: always `"1.0"`; consumers reject anything else.
- `engine`: `"joinmarket"` or `"wasabi"`. Consumers require it to match the
  engine implied by the analysis `--coinjoin-type` (`joinmarket` →
  `joinmarket`, `wasabi2` → `wasabi`); other coinjoin types have no producer
  labels.
- `complete`: `true` only when the engine finished collecting every label
  source. Any collection failure sets `false` and a human-readable `reason`.
- `reason`: `null` when complete, otherwise why capture is not trustworthy.
- `positive_rule`: the rule a consumer applies to the sources to derive
  positive labels (informational; the consumer implements the rule itself).
- `sources`: one record per evidence file, with `path` relative to `data/`
  (forward slashes), exact `size_bytes`, and the SHA-256 of the file content.
  A `complete` manifest with an empty `sources` list is rewritten as
  incomplete by the writer.

## Per-engine source rules

- **JoinMarket** (`JoinMarketRoundEventsMixin.store_engine_logs`): exactly one
  source, `joinmarket_round_events.json`, written before the manifest. The
  positive rule is a reconciled round event whose transaction id appears in
  the exported blocks; see
  [JoinMarket round events](joinmarket-round-events.md).
- **Wasabi, split architecture (2.6)**
  (`WasabiEngine.store_engine_logs`): every `Logs.txt` found under the
  downloaded `wasabi-coordinator/` tree. A failed coordinator download makes
  the manifest incomplete even if backend logs were stored, because the
  coordinator log is the label source.
- **Wasabi, legacy combined backend (2.0.x)**: every `Logs.txt` under the
  downloaded `wasabi-backend/` tree. The positive rule in both Wasabi cases is
  a `Round (<id>): Successfully broadcast the coinjoin: <txid>.` record.
  The consumer accepts case/spacing drift and the legacy `broadcasted` wording.
  Because no captured 2.0.x log fixture is available, it additionally fails
  closed if no broadcast is parsed while exported blocks contain a transaction
  with at least five inputs.

## Writer guarantees

- The manifest is written **after** blocks and engine logs are stored, so the
  hashes cover the final artifact bytes.
- The write is atomic (`.tmp` + `os.replace`), so a partially written manifest
  cannot be mistaken for evidence.
- Source paths are resolved and must stay inside `data/`; anything else marks
  the manifest incomplete instead of recording an escaping path.
- The manifest is included in `emulation_logs.zip` with the rest of `data/`.

## Consumer obligations (summary)

Fail closed. Labels are usable only when all of the following verify:
schema version, engine match, `complete: true`, non-empty `sources`, every
source present with matching size and SHA-256, and every source name allowed
for the engine (`joinmarket_round_events.json` / `Logs.txt`). A verified but
logically empty source remains valid zero-positive evidence. For Wasabi, that
zero-positive interpretation is rejected when exported blocks contain a
transaction with at least five inputs. Producer-positive txids must also all be
present in the exported block set. A Wasabi parseability candidate or unmatched
positive yields unknown labels and no classification metrics.
