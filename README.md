# EmuCoinJoin

A container-based setup for the emulation of CoinJoin transactions on RegTest network.

## Usage

1. Install [Docker](https://docker.com/) or [Podman](https://podman.io/), [Python](http://python.org/), and [uv](https://docs.astral.sh/uv/).
2. Clone the repository `git clone --recurse-submodules https://github.com/crocs-muni/coinjoin-emulator`.
3. Install dependencies: `uv sync`.
4. Run the default scenario with the default driver: `uv run python manager.py run`.
   - [Scenario](#scenarios) definition file can be specified using the `--scenario` option.

For more complex setups see section [Advanced usage](#advanced-usage).

## Scenarios

Scenario definition files can be passed to the simulation script using the `--scenario` option. The scenario definition is a JSON file with the following structure:

```json
{
    "name": "default",
    "rounds": 0,
    "blocks": 120,
    "default_version": "2.0.4",
    "distributor_version": "2.0.4",
    "default_anon_score_target": 5,
    "default_redcoin_isolation": false,
    "backend": {
        "MaxInputCountByRound": 200,
        "MinInputCountByRoundMultiplier": 0.2,
        ...
    },
    "wallets": [
        {"funds": [200000, 50000]},
        {"funds": [3000000], "delay_rounds": 5},
        {"funds": [1000000, 50000], "delay_rounds": 3},
        {"funds": [100000, {"value": 200000, "delay_rounds": 5}]},
        {"funds": [200000], "version": "2.0.3"},
        {"funds": [4000000], "anon_score_target": "25"},
        {"funds": [3500000], "redcoin_isolation": true},
        ...
    ],
}
```

The fields are as follows:
- `name` field is the name of the scenario used for output logs.
- `rounds` field is the number of coinjoin rounds after which the simulation terminates. If set to 0, the simulation will run indefinitely.
- `blocks` field is the number of mined blocks after which the simulation terminates. If set to 0, the simulation will run indefinitely.
- `default_version` field is the string representing of the version of wallet wasabi used for clients without the version specification.
- `distributor_version` field is the string representing of the version of wallet wasabi used for the distributor client.
- `default_anon_score_target` field sets the default value of target anon score.
- `default_redcoin_isolation` field sets the default option for redcoin isolation.
- `backend` field is the configuration for the `wasabi-backend` container used in the simulation. The provided fields update the defaults.
- `wallets` field is a list of wallet configurations. Each wallet configuration is a dictionary with the following fields:
  - `funds` is a list of funds (`int`s or `dict`s) the wallet will use for coinjoins. In case of a dictionary, the following keys are supported:
    - `value` is the amount of funds the wallet will use for coinjoins.
    - `delay_blocks` is the number of blocks the distributor will wait before sending the corresponding funds to the wallet.
    - `delay_rounds` is the number of coinjoin rounds the distributor will wait before sending the corresponding funds to the wallet.
  - `delay_blocks` is the number of blocks the wallet will wait before participating.
  - `delay_rounds` is the number of coinjoin rounds the wallet will wait before participating.
  - `stop_blocks` is the number of blocks after which the wallet will stop participating.
  - `stop_rounds` is the number of rounds after which the wallet will stop participating.
  - `version` is the string representation of wallet wasabi version used for client running this wallet.
  - `anon_score_target` is the target anon score of the wallet.
  - `redcoin_isolation` is a boolean value indicating whether the wallet should use redcoin isolation.

### Nested engine-specific wallet fields

Besides the flat legacy fields above, each wallet accepts nested engine-specific
objects (`manager/engine/configuration.py` supports both spellings):

- `wasabi` — object with `anon_score_target`, `redcoin_isolation`, and
  `skip_rounds` (list of round numbers the wallet skips). The nested values take
  precedence over the flat legacy fields.
- `joinmarket` — object with `role`, either `"maker"` or `"taker"`. The legacy
  flat spelling is `"type": "maker" | "taker"`. Specify a role explicitly for
  every JoinMarket wallet; JoinMarket scenarios with a missing role are
  rejected before containers start. Takers initiate coinjoins (one active
  round at a time), makers provide liquidity. A round only starts once at least
  `JOINMARKET_COUNTERPARTIES` (see `manager/engine/joinmarket/constants.py`)
  makers are running and funded.

### Validation boundaries

Scenario parsing validates the required non-empty strings and wallet list,
strict JSON booleans, non-negative `rounds`, `blocks`, delay, stop, and skipped
round values, and positive fund amounts. Each wallet needs at least one fund.
When `--engine joinmarket` is selected, every wallet additionally requires an
explicit maker/taker role. This is keyed to the selected engine, not to the
text of `default_version`, so custom JoinMarket image tags are validated too.
Invalid input raises `ValueError` before any runtime resources are created.

JoinMarket scenario example:

```json
{
    "name": "default-joinmarket",
    "rounds": 3,
    "blocks": 0,
    "default_version": "joinmarket",
    "wallets": [
        {"funds": [200000, 100000], "joinmarket": {"role": "taker"}},
        {"funds": [1000000, 500000], "delay_blocks": 1, "joinmarket": {"role": "maker"}}
    ]
}
```

## Engine
You can run the simulation with different CoinJoin protocols. Currently, Wasabi and Joinmarket are supported. 
The default protocol is Wasabi. To run the simulation with Joinmarket, use the `--engine joinmarket` option.  

The JoinMarket engine writes `data/joinmarket_round_events.json`. Its schema and
the distinction between lifecycle status and a late block match are documented
in [JoinMarket round events](docs/joinmarket-round-events.md).

Every stored run also contains `data/coinjoin_label_manifest.json`. It records
the selected engine, whether producer-label capture completed, the positive
label rule, and the exact size and SHA-256 digest of every label source. The
manifest is written atomically after service logs are collected and is included
in `emulation_logs.zip`. Consumers must treat a missing, incomplete, or
hash-mismatched manifest as unavailable labels; a verified zero-byte/logically
empty source is a complete capture with zero positives. The full schema and
per-engine source rules are documented in
[Producer label manifest](docs/producer-label-manifest.md).

## Run directory naming

Each `run` invocation stores its artifacts under `./logs/<run-id>/`:

- By default the run id is `<timestamp>_<scenario-name>`, with the timestamp
  rendered in the timezone given by `--run-timezone` (default `Europe/Prague`)
  at minute resolution.
- `--run-id <id>` pins a deterministic directory name instead. The pipeline
  launcher (`coinjoin-pipeline` / `runIt.sh`) uses this to pre-compute the run
  directory and passes it through the `PIPELINE_RUN_ID` environment variable;
  the id must match `[A-Za-z0-9][A-Za-z0-9._-]*`, be at most 63 characters,
  and contain no `..`.
- A pre-existing run directory only counts as a conflict when it already
  contains `coinjoin_emulator_data/` — the launcher may pre-create the empty
  directory to store its host manifest.

`--controller-done-marker` / `--controller-failed-marker` write a marker file
after logs and requested Bitcoin data are stored (or on failure). The
Kubernetes S3 uploader sidecar polls these markers to decide when to sync
artifacts.


## Advanced usage

The simulation script enables advanced configuration for running on different container platforms with various networking setups. This section describes the advanced configuration and shows common examples.

### Backend driver


#### Docker

The default driver is `docker`. Running `docker` requires [Docker](https://www.docker.com/) installed locally and running.

#### Podman

To run the simulation using `podman`, specify it as driver using `--driver podman`, for example `uv run python manager.py --driver podman run`.

The driver requires the [Podman](https://podman.io/) CLI. You may also need to override default IP addresses to communicate via localhost using `--control-ip` and `--wasabi-backend-ip` options.


#### Kubernetes

To run the simulation on a [Kubernetes](https://kubernetes.io/) cluster, use the `kubernetes` driver. The driver requires a running Kubernetes cluster and `kubectl` configured to access the cluster. 

The `kubernetes` driver relies on used images being accessible publicly from [DockerHub](https://hub.docker.com/). For that, build the images in `containers` directory manually and upload them to the registry. Afterwards, specify the image prefix using `--image-prefix` option when starting the simulation.

The manager reaches pod ports through the Kubernetes port-forward API. Services use `ClusterIP` for stable in-cluster DNS, so Kubernetes mode does not require host `NodePort` mappings.

If you need to specify custom namespace, use the `--namespace` option. If you also need to reuse existing namespace, use the `--reuse-namespace` option.

##### Example

Running the simulation on a remote cluster using pre-existing namespace and a proxy reachable on localhost port 8123:
```bash
uv run python manager.py run --driver kubernetes --namespace custom-coinjoin-ns --reuse-namespace --image-prefix "crocsmuni/" --proxy "socks5://127.0.0.1:8123" --scenario "scenarios/uniform-dynamic-500-30utxo.json"
```

### Exporting raw Bitcoin node data

The emulator normally stores scenario, block, client, and wallet data in the log archive. If you need the raw Bitcoin Core data directory for external analysis tools, use `--download-btc-data` to choose a local destination path. The data is copied before containers or pods are cleaned up.

By default, the source is `btc-node:/home/bitcoin/data/`. To export a different container or pod path, pass `--download-path` in `name:/path` format:

```bash
uv run python manager.py run --download-btc-data ./btc-data --download-path btc-node:/home/bitcoin/data/
```
