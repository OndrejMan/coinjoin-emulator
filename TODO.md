# Project Cleanup TODO

- Update `.gitignore` to include all local generated directories, especially `.venv-k3d/`, `.pytest_cache/`, and `.ruff_cache/`.
- Refactor `manager.py` into explicit functions such as `main`, `build_parser`, `create_driver`, `create_engine`, and `run_engine` instead of relying on module-level mutable globals.
- Decide whether the `console` subcommand should be implemented or removed from the CLI.
- Tighten scenario validation in `manager/engine/configuration.py`, including explicit boolean parsing and rejecting unknown JoinMarket roles.
- Add or document a scenario schema so valid Wasabi and JoinMarket fields are discoverable and testable.
- Reduce duplication in `containers/wasabi-clients`, `containers/wasabi-backend`, and `containers/wasabi-coordinator` with manifests or templates for repeated Dockerfile, run script, config, and patch structure.
- Consolidate repeated GitHub Actions image build workflows into a reusable workflow or composite action.
- Replace scattered raw `print()` calls with a small logging/progress abstraction so output verbosity is controllable and tests can assert behavior more cleanly.
- Add a README development section covering `uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run mypy .`, `uv run pylint .`, and generated output directories.
