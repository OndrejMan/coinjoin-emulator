---
name: coinjoin-reading-guide
description: Use when the user is studying this coinjoin-emulator repository and tells Codex which files they have already reviewed, then asks where to look next or how to understand the project incrementally.
---

# CoinJoin Reading Guide

Help the user learn the repository by suggesting the next files to read based on what they have already reviewed.

## Workflow

1. Treat the user's reviewed files as completed context.
2. Recommend the next 1-3 files, not a long generic list, unless they ask for a full map.
3. Explain why each file is next in terms of runtime flow or project architecture.
4. If their current path skipped an important prerequisite, point them back to it briefly.
5. Prefer concrete clickable file references with absolute paths when available.

## Default Reading Path

For a top-down understanding of this repository, use this order:

1. `README.md` for purpose, scenario format, and supported drivers.
2. `manager.py`, `manager/cli.py`, and `manager/application.py` for command dispatch and engine/driver selection.
3. `manager/engine/configuration.py` for scenario parsing and wallet/fund data models.
4. `manager/engine/engine_base.py` for the shared emulator lifecycle.
5. `manager/engine/wasabi_engine.py` for the default Wasabi protocol path.
6. `manager/engine/joinmarket_engine.py` for the JoinMarket protocol path.
7. `manager/driver/__init__.py`, then `manager/driver/docker.py` for the container abstraction and easiest concrete driver.
8. `manager/btc_node.py` for Bitcoin Core RPC, mining, wallet creation, and funding.
9. Wasabi adapters: `manager/wasabi_clients/wasabi_client_base.py`, version-specific client classes, `manager/wasabi_backend.py`, `manager/wasabi_backend_26.py`, `manager/wasabi_coordinator.py`, and `manager/wasabi_backend_factory.py`.
10. JoinMarket adapter: `manager/wasabi_clients/joinmarket_client.py`.
11. Tests as executable documentation, especially `tests/test_configuration.py`, `tests/test_engine_base.py`, `tests/test_application.py`, `tests/test_joinmarket_engine.py`, and driver tests.

## Architecture Summary

Use this mental model when guiding the user:

`cli.py` parses command-line arguments. `application.py` creates a driver and selected engine. `EngineBase` owns the generic scenario lifecycle. Concrete engines implement protocol-specific containers and coinjoin behavior. Drivers run and inspect containers or pods. Client/backend wrappers are thin RPC adapters around Wasabi, JoinMarket, and Bitcoin Core services.

## Response Style

Keep answers short and directional. The user is reading code, so prioritize "read this next because..." over comprehensive summaries.
