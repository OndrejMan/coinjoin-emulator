"""An unreachable Wasabi client must name itself and its container state."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from manager.engine.wasabi_engine import WasabiEngine
from manager.wasabi_backend_factory import BackendArchitecture


def engine(container_state) -> WasabiEngine:
    instance = object.__new__(WasabiEngine)
    instance.args = SimpleNamespace()
    instance.clients = []
    instance.driver = Mock()
    instance.driver.container_state.return_value = container_state
    return instance


def client() -> Mock:
    instance = Mock()
    instance.name = "wasabi-client-003"
    instance.host = "172.19.0.2"
    instance.port = 30746
    instance.start_coinjoin.side_effect = requests.exceptions.ConnectionError(
        "Connection refused"
    )
    return instance


def test_a_dead_client_is_named_together_with_its_pod_phase() -> None:
    """The bare ConnectionError reads as a network fault; it is a dead client."""
    with pytest.raises(RuntimeError) as raised:
        engine("pod phase Succeeded").start_coinjoin(client())

    message = str(raised.value)
    assert "wasabi-client-003" in message
    assert "pod phase Succeeded" in message
    # The reader has to be sent to the client's own log, where the real
    # exception is; nothing else in the run records it.
    assert "own log" in message


def test_an_undiscoverable_container_state_still_names_the_client() -> None:
    """A driver that cannot answer must not replace the error with its own."""
    instance = engine(None)
    instance.driver.container_state.side_effect = RuntimeError("driver is gone")

    with pytest.raises(RuntimeError) as raised:
        instance.start_coinjoin(client())

    message = str(raised.value)
    assert "wasabi-client-003" in message
    assert "container state unknown" in message
    assert "driver is gone" not in message


def test_the_original_error_is_kept_as_the_cause() -> None:
    with pytest.raises(RuntimeError) as raised:
        engine("pod phase Succeeded").start_coinjoin(client())

    assert isinstance(raised.value.__cause__, requests.exceptions.ConnectionError)


def test_the_infrastructure_state_covers_every_shared_wasabi_container(capsys) -> None:
    instance = engine("pod phase Running")
    instance.backend_architecture = BackendArchitecture.SPLIT

    instance.report_infrastructure_state()

    assert capsys.readouterr().out.splitlines() == [
        "Infrastructure state",
        "- btc-node: pod phase Running",
        "- wasabi-backend: pod phase Running",
        "- wasabi-coordinator: pod phase Running",
        "- wasabi-client-distributor: pod phase Running",
    ]


def test_the_infrastructure_state_also_names_every_client(capsys) -> None:
    """A run that fails after setup usually lost a client, so its pod state is listed too."""
    instance = engine("pod phase Running")
    instance.backend_architecture = BackendArchitecture.SPLIT
    instance.clients = [SimpleNamespace(name="wasabi-client-000"), SimpleNamespace(name="wasabi-client-001")]
    instance.driver.container_state.side_effect = lambda name: (
        "pod phase Succeeded; container terminated: Completed (exit code 0)"
        if name == "wasabi-client-001" else "pod phase Running"
    )

    instance.report_infrastructure_state()

    assert capsys.readouterr().out.splitlines()[-2:] == [
        "- wasabi-client-000: pod phase Running",
        "- wasabi-client-001: pod phase Succeeded; container terminated: Completed (exit code 0)",
    ]


def dead_wallet() -> Mock:
    instance = Mock()
    instance.name = "wasabi-client-006"
    instance.list_coins.side_effect = requests.exceptions.ConnectionError("[Errno 111] Connection refused")
    return instance


def test_a_wallet_that_stopped_answering_leaves_its_container_output(tmp_path, capsys, monkeypatch) -> None:
    """Its coins and keys are lost with it; the run still fails, but the exception that ended Wasabi is kept."""
    monkeypatch.setattr("manager.engine.engine_base.sleep", lambda _seconds: None)
    instance = engine("pod phase Succeeded; container terminated: Completed (exit code 0)")
    output = "".join(f"line {number}\n" for number in range(100)) + "Unhandled exception. System.IndexOutOfRangeException\n"
    instance.driver.logs.return_value = output

    with pytest.raises(requests.exceptions.ConnectionError):
        instance.store_client_logs(dead_wallet(), str(tmp_path))

    assert (tmp_path / "wasabi-client-006" / "container.log").read_text(encoding="utf-8") == output
    printed = capsys.readouterr().out
    assert "- wasabi-client-006 container state: pod phase Succeeded; container terminated: Completed (exit code 0)" in printed
    assert "  | Unhandled exception. System.IndexOutOfRangeException" in printed
    assert "  | line 60" not in printed
    assert "  | line 61" in printed
    instance.driver.download.assert_not_called()


def test_an_unreadable_container_log_keeps_the_wallet_error(tmp_path, capsys, monkeypatch) -> None:
    """The cleanup must report the refused wallet, not the driver's own failure."""
    monkeypatch.setattr("manager.engine.engine_base.sleep", lambda _seconds: None)
    instance = engine(None)
    instance.driver.logs.side_effect = RuntimeError("pod not found")

    with pytest.raises(requests.exceptions.ConnectionError):
        instance.store_client_logs(dead_wallet(), str(tmp_path))

    printed = capsys.readouterr().out
    assert "- wasabi-client-006 container state: unknown" in printed
    assert "could not store wasabi-client-006 container log: RuntimeError('pod not found')" in printed
    assert not (tmp_path / "wasabi-client-006" / "container.log").exists()
