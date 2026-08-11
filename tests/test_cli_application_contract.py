"""Fast CLI and lifecycle checks for the pipeline-facing manager contract."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from manager import cli
from manager.application import run_engine


def test_compose_argument_vector_is_parsed_without_starting_a_driver() -> None:
    dispatcher = Mock(return_value=0)
    argv = [
        "--engine", "joinmarket", "--driver", "docker", "run",
        "--namespace", "compose-test", "--scenario", "scenario.json",
        "--btc-node-arg=-blocksxor=0", "--download-btc-data", "btc-data",
        "--download-path", "btc-node:/bitcoin/data/",
    ]

    assert cli.main(argv, dispatcher=dispatcher) == 0
    args = dispatcher.call_args.args[0]
    assert args.engine == "joinmarket"
    assert args.driver == "docker"
    assert args.namespace == "compose-test"
    assert args.btc_node_arg == ["-blocksxor=0"]
    assert args.download_path == "btc-node:/bitcoin/data/"


def test_in_cluster_argument_vector_accepts_global_branch_options() -> None:
    dispatcher = Mock(return_value=0)
    argv = [
        "--driver", "kubernetes", "--in-cluster", "--namespace", "coinjoin",
        "--reuse-namespace", "--engine", "joinmarket", "run",
        "--image-prefix", "registry.example/", "--scenario", "/work/scenario.json",
        "--k8s-pull-secret", "/work/config.json",
    ]

    assert cli.main(argv, dispatcher=dispatcher) == 0
    args = dispatcher.call_args.args[0]
    assert args.in_cluster
    assert args.reuse_namespace
    assert args.k8s_pull_secret == "/work/config.json"
    assert args.scenario == "/work/scenario.json"


def test_create_kubernetes_driver_preserves_branch_specific_constructor_arguments() -> None:
    args = SimpleNamespace(
        driver="kubernetes", namespace="coinjoin", reuse_namespace=True,
        k8s_pull_secret="/work/config.json", in_cluster=True,
    )

    with patch("manager.cli.KubernetesDriver") as driver:
        cli.create_driver(args)

    driver.assert_called_once_with("coinjoin", True, "/work/config.json", True, None)


def test_create_kubernetes_driver_detects_in_cluster_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    args = SimpleNamespace(
        driver="kubernetes",
        namespace="coinjoin",
        reuse_namespace=True,
        k8s_pull_secret=None,
        in_cluster=False,
        disable_port_forward=True,
        proxy="",
        run_id="run-1",
    )
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")

    with patch("manager.cli.KubernetesDriver") as driver:
        cli.create_driver(args)

    driver.assert_called_once_with("coinjoin", True, None, True, "run-1")


def test_system_exit_writes_a_failure_marker_after_all_cleanup_attempts(tmp_path: Path) -> None:
    args = SimpleNamespace(
        no_logs=False,
        download_btc_data="",
        download_path="btc-node:/home/bitcoin/data/",
        image_prefix="",
        controller_done_marker=str(tmp_path / "done"),
        controller_failed_marker=str(tmp_path / "failed"),
    )
    driver = Mock()
    engine = Mock()
    engine.node = Mock()
    engine.run.side_effect = SystemExit(143)
    engine.stop_coinjoins.side_effect = RuntimeError("stop failed")
    engine.store_logs.side_effect = RuntimeError("logs failed")

    assert run_engine(args, driver, engine) == 1
    engine.stop_coinjoins.assert_called_once_with()
    engine.shutdown_engine.assert_called_once_with()
    engine.store_logs.assert_called_once_with()
    driver.cleanup.assert_called_once_with("")
    assert (tmp_path / "failed").read_text(encoding="utf-8") == "done\n"
    assert not (tmp_path / "done").exists()


def test_cleanup_skips_btc_download_before_node_initialization(tmp_path: Path) -> None:
    args = SimpleNamespace(
        no_logs=False,
        download_btc_data=str(tmp_path / "btc-data"),
        download_path="btc-node:/home/bitcoin/data/",
        image_prefix="",
        controller_done_marker=str(tmp_path / "done"),
        controller_failed_marker=str(tmp_path / "failed"),
    )
    driver = Mock()
    engine = Mock(node=None)
    engine.run.side_effect = RuntimeError("image build failed")
    downloader = Mock()

    assert run_engine(args, driver, engine, downloader) == 1

    downloader.assert_not_called()
    driver.cleanup.assert_called_once_with("")
