"""Command-line contract the pipeline launcher relies on."""

import importlib.util
import runpy
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "manager.py"


def load_entrypoint() -> ModuleType:
    spec = importlib.util.spec_from_file_location("manager_entrypoint", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse(*argv: str):
    return load_entrypoint().build_parser().parse_args(list(argv))


@pytest.mark.parametrize("in_cluster", [False, True])
@pytest.mark.parametrize("service_host", [None, "10.43.0.1"])
def test_driver_mode_is_selected_only_by_the_explicit_flag(monkeypatch, in_cluster, service_host):
    from manager.driver import kubernetes

    if service_host is None:
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    else:
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", service_host)
    argv = [str(ENTRYPOINT), "--driver", "kubernetes"]
    if in_cluster:
        argv.append("--in-cluster")
    argv.append("run")
    monkeypatch.setattr(sys, "argv", argv)
    # Stop at driver construction so the real CLI runs without cluster access.
    driver = Mock(side_effect=RuntimeError("driver construction reached"))
    monkeypatch.setattr(kubernetes, "KubernetesDriver", driver)

    with pytest.raises(RuntimeError, match="driver construction reached"):
        runpy.run_path(str(ENTRYPOINT), run_name="__main__")

    assert driver.call_args.kwargs["in_cluster"] is in_cluster


def test_service_host_does_not_authorize_disabling_port_forward(monkeypatch, capsys):
    from manager.driver import kubernetes

    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.43.0.1")
    monkeypatch.setattr(sys, "argv", [
        str(ENTRYPOINT), "--driver", "kubernetes", "run", "--disable-port-forward",
    ])
    driver = Mock()
    monkeypatch.setattr(kubernetes, "KubernetesDriver", driver)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(ENTRYPOINT), run_name="__main__")

    assert exit_info.value.code == 1
    driver.assert_not_called()
    assert "requires --proxy or --in-cluster" in capsys.readouterr().out
