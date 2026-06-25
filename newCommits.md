1. chore: add uv-based Python project tooling

Adds pyproject.toml, uv.lock, .gitignore updates, .dockerignore, and updates README commands from pip/python to uv run.

Purpose: make the repo reproducible and easier to test.

2. ci: add static analysis workflow

Adds GitHub Actions for:

uv run pytest
uv run ruff check .
uv run mypy .
uv run pylint .

Purpose: quality gate before bigger refactor.

3. refactor: introduce emulator-specific exceptions

Adds custom exceptions like:

CoinjoinEmulatorError
StartupError
RpcError

Purpose: avoid throwing generic Exception everywhere.

4. refactor: type Bitcoin Core RPC wrapper

Cleans up manager/btc_node.py:

adds type hints,
adds RpcError,
types RPC responses,
keeps wallet-path RPC support.

Purpose: make Bitcoin RPC safer before JoinMarket funding depends on it.

5. feat: support named Bitcoin Core wallets

Adds/cleans functionality for per-wallet RPC calls, probably something like:

/wallet/<wallet_name>

Purpose: JoinMarket clients need isolated Bitcoin Core wallets instead of one shared wallet.

This is a thesis-relevant commit.

6. refactor: define typed driver and engine protocols

Adds Protocols/interfaces for things like:

DriverProtocol
EngineArgs
EmulatorClient
InvoiceDistributor

Purpose: make engine code testable without real Docker/Kubernetes.

7. refactor: clean manager entrypoint and command dispatch

Cleans manager.py / CLI flow:

parse args,
choose driver,
choose engine,
handle run, clean, genscen,
replace exit() with sys.exit().

Purpose: make main program easier to reason about and test.

8. feat: improve driver lifecycle with logs and volumes

Changes Docker/Podman/Kubernetes driver behavior:

support volumes,
expose logs,
improve cleanup,
avoid losing logs immediately after failure.

Purpose: JoinMarket debugging needs persistent logs and mounted data.

9. feat: add JoinMarket client-server container

Adds container files for JoinMarket:

Dockerfile,
startup script,
patches,
regtest config.

Purpose: make JoinMarket runnable inside the emulator.

This is another core thesis commit.

10. feat: add JoinMarket client RPC wrapper

Adds/cleans JoinMarketClientServer wrapper:

wait for wallet,
get status,
get balance,
create invoices,
start maker,
start taker/send payment,
stop coinjoin process.

Purpose: Python emulator can control JoinMarket clients.

11. feat: extend scenario config for JoinMarket wallets

Adds config structures like:

JoinMarketConfig
JoinMarketRole

and supports nested wallet config:

{
  "joinmarket": {
    "role": "maker"
  }
}

Purpose: scenario files can describe maker/taker clients.

12. feat: add default JoinMarket scenario

Adds a default scenario with:

multiple makers,
at least one taker,
JoinMarket-specific wallet settings,
enough funds for testing.

Purpose: easy reproducible test case.

13. feat: start JoinMarket infrastructure

Adds JoinMarket engine infrastructure:

IRC server,
distributor/client server,
per-client startup,
per-client Bitcoin Core wallet creation.

Purpose: boot all services needed before actual CoinJoin rounds.

14. feat: fund JoinMarket clients through Bitcoin Core

Implements funding flow:

create JoinMarket deposit invoices,
pay them from Bitcoin Core,
mine blocks,
confirm balances.

Purpose: clients actually receive regtest coins and can participate.

Very important commit.

15. feat: orchestrate JoinMarket maker and taker rounds

Implements actual JoinMarket behavior:

start makers,
detect running makers,
start taker round,
enforce one active round,
wait/mine blocks,
retry/timeout behavior.

Purpose: this is the main PoC behavior.

16. feat: record JoinMarket round events

Stores events like:

{
  "round_id": 1,
  "taker": "jcs-001",
  "destination_address": "...",
  "status": "started"
}

Purpose: later analysis can map JoinMarket activity to blocks/transactions.

17. feat: match JoinMarket rounds to mined blocks

Scans exported Bitcoin Core block data and matches JoinMarket destination outputs to transactions/blocks.

Purpose: connect emulator-level events to blockchain-level analysis.

18. test: cover JoinMarket, Bitcoin RPC, config, and drivers

Adds/updates tests for:

Bitcoin wallet RPC path,
JoinMarket scenario parsing,
default JoinMarket scenario,
JoinMarket client wrapper,
JoinMarket engine orchestration,
Docker driver volumes/logs,
manager/CLI behavior.

Purpose: prove the stack works.

Optional final commit
docs: document JoinMarket emulator flow and known limitations

Add a short docs/joinmarket.md or README section:

Scenario config -> engine -> containers -> Bitcoin Core wallets -> invoice funding -> maker/taker round -> block export -> round matching

Also list limitations:

hardcoded coinjoin amount,
limited maker/taker parameters,
no tumbler schedule support,
basic round detection,
PoC-level error handling.

This helps a lot for thesis defense.

Best order for your reimplementation

I would not start with typing/refactor. I would do this order:

Bitcoin Core wallet/RPC support
JoinMarket container
JoinMarket client wrapper
Scenario config
JoinMarket engine startup
Funding
Maker/taker orchestration
Round detection/export
Tests
Tooling/refactor cleanup

Final target: around 15 commits, each one explainable in 2–3 sentences. That is much better than one vibe-coded mega-commit.