# Integration plan for `rajnoha-on-crocs`

This document describes how to review and integrate the rewritten history on
top of David Rajnoha's immutable work. It is intentionally stored in the last,
documentation-only commit so it can be dropped after the integration if the
upstream repository does not want to retain it.

## Immutable baseline and safety references

- Immutable baseline: `dd87648` (`chore: Update scenario generation scripts for injected takers experiment`)
- Original rewritten-equivalence tip: `mr-09-e2e-hardening` (`5e45a8b`)
- Current integration tip: `mr-11-kubernetes-wasabi-hardening`
- Original pre-rewrite tip: `e36e32e`
- Original-history backup: `backup/rajnoha-on-crocs-pre-rewrite-20260812`
- First rewrite backup: `backup/rajnoha-on-crocs-87-commits`
- Pre-cleanup WIP backup: `backup/rebased-rajnoha-on-crocs-pre-cleanup-20260829`
- The tree at `5e45a8b` is identical to the tree at the original `e36e32e`.
- Every commit after `dd87648` is authored by `Ondrej Man <ondrejman1@gmail.com>`.
- None of the rewritten commits contains a Claude/Codex or `Co-authored-by` trailer.

The five Claude trailers reachable below `dd87648` belong to David's immutable
commits and are deliberately left unchanged.

## Proposed merge requests

The ranges below are disjoint and together contain all 173 Ondrej-owned
commits after the immutable baseline. `Base` is excluded and `Tip` is included,
matching `git log Base..Tip`.

| MR | Suggested title | Base | Tip | Boundary tag | Commits | Suggested labels | Depends on |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| MR 1 | Stabilize inherited emulator runtime contracts | `dd87648` | `df8e137` | `mr-01-runtime-contracts` | 25 | `bugfix`, `runtime`, `integration` | David's immutable baseline |
| MR 2 | Add deterministic artifacts and producer labels | `df8e137` | `01920d8` | `mr-02-artifact-contract` | 6 | `feature`, `artifacts`, `joinmarket` | MR 1 |
| MR 3 | Add reproducible builds and static analysis | `01920d8` | `da8f8f1` | `mr-03-build-static-analysis` | 12 | `build`, `ci`, `testing`, `typing` | MR 2 |
| MR 4 | Complete strict typing and structured logging | `da8f8f1` | `4998bf0` | `mr-04-typing-logging` | 20 | `refactor`, `typing`, `logging` | MR 3 |
| MR 5 | Split JoinMarket and engine responsibilities | `4998bf0` | `f25c7d0` | `mr-05-engine-refactor` | 17 | `refactor`, `joinmarket`, `engine` | MR 4 |
| MR 6 | Add focused engine and client contract tests | `f25c7d0` | `ada32c7` | `mr-06-contract-tests` | 11 | `tests`, `joinmarket`, `wasabi`, `engine` | MR 5 |
| MR 7 | Finish lint cleanup and post-refactor fixes | `ada32c7` | `73beeaf` | `mr-07-lint-post-refactor` | 17 | `maintenance`, `lint`, `bugfix`, `refactor` | MR 4–6 |
| MR 8 | Harden remote orchestration and image integration | `73beeaf` | `5210290` | `mr-08-remote-image-integration` | 9 | `bugfix`, `remote`, `kubernetes`, `ci`, `images` | MR 5 and MR 7 |
| MR 9 | Apply end-to-end runtime hardening | `5210290` | `5e45a8b` | `mr-09-e2e-hardening` | 38 | `bugfix`, `e2e`, `docker`, `podman`, `kubernetes`, `joinmarket`, `bitcoin` | MR 1–8 |
| MR 10 | Restore parity with the current `main` runtime | `5e45a8b` | `mr-10-main-parity-hardening` | `mr-10-main-parity-hardening` | 13 | `bugfix`, `parity`, `docker`, `podman`, `kubernetes`, `joinmarket`, `wasabi` | MR 9 |
| MR 11 | Harden Kubernetes Wasabi integration | `mr-10-main-parity-hardening` | `mr-11-kubernetes-wasabi-hardening` | `mr-11-kubernetes-wasabi-hardening` | 5 | `bugfix`, `kubernetes`, `wasabi`, `bitcoin`, `integration` | MR 10 |

The annotated `mr-*` tags are the canonical visible separators. Display them
directly in the history with:

```bash
git log --decorate --oneline dd87648..mr-11-kubernetes-wasabi-hardening
```

### MR 1 – Stabilize inherited emulator runtime contracts

This MR ports the correctness expectations from `main` onto David's baseline:
explicit failures, Bitcoin and Wasabi timeout handling, validated funding,
JoinMarket startup checks, and remote runner contracts. It intentionally
contains no artifact-layout feature or structural refactoring.

Review with:

```bash
git log --oneline dd87648..df8e137
git diff dd87648..df8e137
```

### MR 2 – Add deterministic artifacts and producer labels

This MR adds deterministic run identity, controller completion markers,
artifact layout, producer-label manifests, and JoinMarket round-event export.
These changes form one evidence contract consumed by downstream analysis.

Review with:

```bash
git log --oneline df8e137..01920d8
git diff df8e137..01920d8
```

### MR 3 – Add reproducible builds and static analysis

This MR adds image publishing, uv metadata, Python 3.11 image setup, lint/type
configuration, CI checks, and the archive/pipeline contract tests needed to
guard the packaging boundary.

Review with:

```bash
git log --oneline 01920d8..da8f8f1
git diff 01920d8..da8f8f1
```

### MR 4 – Complete strict typing and structured logging

This is a mechanical typing migration plus the structured logging module.
Reviewers should evaluate the logging commit separately, then review the type
commits by subsystem. The final commit removes the temporary mypy opt-outs.

Review with:

```bash
git log --oneline da8f8f1..4998bf0
git diff da8f8f1..4998bf0
```

### MR 5 – Split JoinMarket and engine responsibilities

This MR is intended to be behavior-preserving. It extracts the JoinMarket
wallet client, JoinMarket engine lifecycle, and shared engine services into
small modules. Each extraction is a separate commit so moved code can be
reviewed with rename detection enabled.

Review with:

```bash
git log --oneline 4998bf0..f25c7d0
git diff --find-renames 4998bf0..f25c7d0
```

### MR 6 – Add focused engine and client contract tests

This MR adds tests for logging, Wasabi retries, JoinMarket evidence, wallet and
RPC behavior, distributor funding, startup retries, and per-round updates.

Review with:

```bash
git log --oneline f25c7d0..ada32c7
git diff f25c7d0..ada32c7
```

### MR 7 – Finish lint cleanup and post-refactor fixes

This MR contains mechanical formatting and lint cleanup followed by isolated
correctness fixes exposed by the stricter checks. Behavior-changing fixes are
kept in their own commits and are not squashed into formatting commits.

Review with:

```bash
git log --oneline ada32c7..73beeaf
git diff ada32c7..73beeaf
```

### MR 8 – Harden remote orchestration and image integration

This MR fixes label evidence, Kubernetes schedule discovery, remote deployment
patching, bitcoind initialization, image publication names, build arguments,
and scenario-runner CI coverage.

Review with:

```bash
git log --oneline 73beeaf..5210290
git diff 73beeaf..5210290
```

### MR 9 – Apply end-to-end runtime hardening

This MR contains failures discovered during end-to-end and MetaCentrum
validation. The commits remain deliberately small because they cover distinct
failure modes across CLI configuration, Docker, Podman, Kubernetes, Bitcoin,
JoinMarket, artifact collection, cleanup, and image execution.

Review with:

```bash
git log --oneline 5210290..5e45a8b
git diff 5210290..5e45a8b
```

### MR 10 – Restore parity with the current `main` runtime

This block preserves David Rajnoha's internal architecture while restoring the
runtime guarantees added to `main` after the original rewrite. The first five
runtime commits replace the mixed `Small fixes` and `WIP` suffix with atomic
commits; the tree at `2711ff6` is identical to the old development tip
`817f776`. The remaining commits port only behavior that is still needed:

- complete JoinMarket address evidence, including already-spent inputs;
- explicit Kubernetes exec readiness and safe handling of live-tar warnings;
- reservation of Wasabi's fixed service ports with a Kubernetes compatibility
  fallback; and
- bounded retries for known transient Wasabi coordinator startup failures.

The `main`-only extraction of its local port-forward class and the test-helper
file move are deliberately absent. Rajnoha's branch uses a different remote
proxy architecture, and those two changes do not add a missing runtime
contract here.

Review with:

```bash
git log --oneline mr-09-e2e-hardening..mr-10-main-parity-hardening
git diff mr-09-e2e-hardening..mr-10-main-parity-hardening
```

### MR 11 – Harden Kubernetes Wasabi integration

This block contains four atomic runtime changes discovered while exercising
the local Kubernetes-to-S3 Wasabi path:

- allow constrained integration runs to request a shorter initial regtest
  chain while preserving the production default of 1001 blocks;
- allow locally imported k3d images to use `IfNotPresent` without changing the
  production `Always` pull-policy default;
- use the exposed Kubernetes Service port for in-cluster controller endpoints
  while preserving proxy and external NodePort behavior; and
- pass the initialized split Wasabi coordinator address to the distributor.

The runtime code tip is the commit immediately before the documentation-only
tip. The fifth commit only updates this integration plan, so reviewers can drop
it if the upstream repository does not want to retain review-process
documentation.

Review with:

```bash
git log --oneline mr-10-main-parity-hardening..mr-11-kubernetes-wasabi-hardening
git diff mr-10-main-parity-hardening..mr-11-kubernetes-wasabi-hardening
```

## Recommended integration workflow

### Option A: stacked merge requests

Create one branch from every annotated MR boundary tag:

```bash
git branch review/mr-01-runtime-contracts mr-01-runtime-contracts
git branch review/mr-02-artifact-contract mr-02-artifact-contract
git branch review/mr-03-build-and-analysis mr-03-build-static-analysis
git branch review/mr-04-typing-and-logging mr-04-typing-logging
git branch review/mr-05-engine-refactor mr-05-engine-refactor
git branch review/mr-06-contract-tests mr-06-contract-tests
git branch review/mr-07-lint-and-fixes mr-07-lint-post-refactor
git branch review/mr-08-remote-integration mr-08-remote-image-integration
git branch review/mr-09-e2e-hardening mr-09-e2e-hardening
git branch review/mr-10-main-parity mr-10-main-parity-hardening
git branch review/mr-11-kubernetes-wasabi mr-11-kubernetes-wasabi-hardening
```

Open MR 1 against the branch containing `dd87648`. Open every following MR
against the previous review branch, not directly against the immutable
baseline. This makes every MR show only its own disjoint commit range.

Merge the MRs in numerical order. After merging an earlier MR, retarget or
rebase only the later Ondrej-owned review branches. Never rewrite the baseline
through `dd87648`.

### Option B: sequential merge requests

If stacked MRs are inconvenient, create and merge only MR 1. Then create MR 2
from `01920d8` against the branch containing the merged MR 1, and continue in
order. This avoids temporary stacked targets at the cost of waiting for each MR
to merge before opening the next one.

## Verification before publishing

The original rewrite through MR 9 was verified with an identical tree
comparison against the original tip and with focused unit tests:

```text
26 passed
```

The MR 11 runtime suffix was checked before and after the WIP-history cleanup:

```text
45 passed
Ruff: all checks passed
```

Before publishing the final stack, verify the branch boundaries and trailers:

```bash
git diff --exit-code backup/rajnoha-on-crocs-pre-rewrite-20260812..mr-09-e2e-hardening
git log --format='%H%n%B%n---' dd87648..mr-11-kubernetes-wasabi-hardening \
  | rg -i 'co-authored-by|claude|codex'
git rev-list --count dd87648..mr-11-kubernetes-wasabi-hardening
git rev-list --count mr-10-main-parity-hardening..mr-11-kubernetes-wasabi-hardening
```

The first command must produce no output. The second command must also produce
no output because it intentionally searches only the rewritten Ondrej-owned
suffix. The two counts must be `173` and `5`, respectively.

Do not delete the backup branches until all merge requests have been reviewed,
the MR 9 equivalence check has passed, and the cleaned MR 11 branch has been
published and reviewed.
