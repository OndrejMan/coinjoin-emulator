"""The distributor startup timeout must be configurable, not hard-coded.

The distributor downloads a block filter for every block already in the chain
before its wallet answers, so the wait is a function of chain length and host
load, not a constant the emulator can pick once for every driver.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

from manager import cli
from manager.driver import Driver
from manager.engine.base.protocols import EngineArgs
from manager.engine.wasabi_engine import DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT, WasabiEngine
from manager.exceptions import StartupError


def engine_args(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "command": "run",
        "scenario": None,
        "image_prefix": "registry/",
        "proxy": "",
        "in_cluster": False,
        "control_ip": "localhost",
        "btc_node_ip": "",
        "wasabi_backend_ip": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def distributor_engine(args: SimpleNamespace, wallet_ready: bool) -> tuple[WasabiEngine, Mock]:
    driver = Mock()
    driver.in_cluster = False
    driver.run.return_value = ("10.0.0.5", {37128: 37131}, None)
    engine = WasabiEngine(cast(EngineArgs, args), cast(Driver, driver))
    engine.node = Mock(internal_ip="btc-node")
    engine.backend = Mock(internal_ip="wasabi-backend")
    distributor = Mock()
    distributor.wait_wallet.return_value = wallet_ready
    return engine, distributor


def start_distributor(args: SimpleNamespace, wallet_ready: bool = True) -> Mock:
    engine, distributor = distributor_engine(args, wallet_ready)
    with patch.object(WasabiEngine, "init_wasabi_client", return_value=distributor):
        engine.start_distributor()
    return distributor


def test_configured_timeout_reaches_the_distributor_wallet_wait() -> None:
    distributor = start_distributor(engine_args(distributor_startup_timeout=1234))

    distributor.wait_wallet.assert_called_once_with(timeout=1234)


def test_missing_option_falls_back_to_the_module_default() -> None:
    distributor = start_distributor(engine_args())

    distributor.wait_wallet.assert_called_once_with(
        timeout=DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT
    )


def test_timed_out_distributor_still_fails_the_run() -> None:
    engine, distributor = distributor_engine(
        engine_args(distributor_startup_timeout=5), wallet_ready=False
    )

    with patch.object(WasabiEngine, "init_wasabi_client", return_value=distributor):
        with pytest.raises(StartupError, match="Could not start distributor"):
            engine.start_distributor()


def parsed_run_args(argv: list[str]) -> SimpleNamespace:
    dispatcher = Mock(return_value=0)
    assert cli.main(["run", *argv], dispatcher=dispatcher) == 0
    return cast(SimpleNamespace, dispatcher.call_args.args[0])


def test_command_line_option_overrides_the_default() -> None:
    args = parsed_run_args(["--distributor-startup-timeout", "1500"])

    assert args.distributor_startup_timeout == 1500


def test_environment_supplies_the_default_for_templated_command_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(cli.DISTRIBUTOR_STARTUP_TIMEOUT_ENV, "1800")

    assert parsed_run_args([]).distributor_startup_timeout == 1800


def test_command_line_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.DISTRIBUTOR_STARTUP_TIMEOUT_ENV, "1800")

    args = parsed_run_args(["--distributor-startup-timeout", "600"])

    assert args.distributor_startup_timeout == 600


@pytest.mark.parametrize("value", ["", "   ", "not-a-number", "0", "-30"])
def test_unusable_environment_value_falls_back_instead_of_failing_the_run(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(cli.DISTRIBUTOR_STARTUP_TIMEOUT_ENV, value)

    assert (
        parsed_run_args([]).distributor_startup_timeout
        == DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT
    )


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_unusable_command_line_value_is_rejected(value: str) -> None:
    with pytest.raises(SystemExit):
        parsed_run_args(["--distributor-startup-timeout", value])
