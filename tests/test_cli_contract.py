"""Command-line contract the pipeline launcher relies on."""

import importlib.util
from pathlib import Path
from types import ModuleType

ENTRYPOINT = Path(__file__).resolve().parents[1] / "manager.py"


def load_entrypoint() -> ModuleType:
    spec = importlib.util.spec_from_file_location("manager_entrypoint", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse(*argv: str):
    return load_entrypoint().build_parser().parse_args(list(argv))


def test_the_distributor_startup_timeout_defaults_to_the_engine_constant() -> None:
    from manager.engine.wasabi_engine import DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT

    assert parse("run").distributor_startup_timeout == DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT


def test_the_distributor_startup_timeout_can_come_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("COINJOIN_DISTRIBUTOR_STARTUP_TIMEOUT", "1500")

    assert parse("run").distributor_startup_timeout == 1500


def test_an_unusable_distributor_startup_timeout_falls_back_to_the_default(monkeypatch) -> None:
    from manager.engine.wasabi_engine import DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT

    monkeypatch.setenv("COINJOIN_DISTRIBUTOR_STARTUP_TIMEOUT", "not-a-number")

    assert parse("run").distributor_startup_timeout == DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT
