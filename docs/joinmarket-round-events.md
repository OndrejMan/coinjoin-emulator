# JoinMarket round events

The JoinMarket engine writes `data/joinmarket_round_events.json` when it stores
run artifacts. The file is intended to connect an attempted taker round with a
transaction found in exported Bitcoin blocks.

## Main fields

- `round_id`: emulator attempt number;
- `status`: lifecycle status such as `started`, `confirmed`, or `failed`;
- `taker`, `candidate_makers`, `counterparties`, and amount/mixdepth settings;
- `destination_address`: address used to match the attempt to an exported
  transaction output;
- `txid`, `block_height`, and `match_source`: block-match result;
- `confirmed_block`: emulator block counter when an event was confirmed or
  reconciled against exported blocks;
- `failure_reason`, `stop_block`, and retry metadata for failed attempts.
- `status_before_chain_reconciliation` and
  `failure_reason_before_chain_reconciliation`: preserved history when final
  block evidence changes an earlier terminal status;
- `late_confirmation`: true when a previously failed attempt is found on chain.

## Lifecycle status versus block evidence

During a run, events still in `started` state are promoted to `confirmed` by
the live confirmation loop. An attempt can first be marked `failed` because
its taker stopped and then be found in exported blocks at artifact-storage
time. The final matching pass treats chain evidence as authoritative: it sets
`status = "confirmed"`, adds `txid`, `block_height`, and
`match_source = "destination_output"`, and preserves the former lifecycle
state and reason in the reconciliation-history fields.

Therefore:

- `status = "confirmed"` plus a non-null `txid` and block match is final
  positive chain evidence;
- `late_confirmation = true` identifies a round that was initially treated as
  failed but was reconciled later;
- a remaining `status = "failed"` record has no matched transaction in the
  exported block set used by the final pass.

Consumers should retain the reconciliation history for lifecycle diagnostics,
but use the final status/block match for transaction labels. The pipeline
records the producer file and label rule in report provenance.

## Capture completeness

The companion `data/coinjoin_label_manifest.json` is the completeness boundary
for this file. A complete JoinMarket manifest names
`joinmarket_round_events.json` and records its byte size and SHA-256 digest.
The analyzer verifies all three before using the event list. An empty JSON list
is legitimate complete evidence with no positive transactions; file presence
without a valid manifest is not evidence that artifact collection finished.
