from types import SimpleNamespace
from unittest.mock import Mock

from manager import cli
from manager.application import DEFAULT_BTC_DOWNLOAD_PATH


def command_args(command: str, **overrides: object) -> SimpleNamespace:
    return SimpleNamespace(command=command, **overrides)


def test_main_parses_run_arguments_and_dispatches() -> None:
    dispatch = Mock(return_value=7)

    exit_code = cli.main(
        [
            "--engine",
            "joinmarket",
            "--driver",
            "kubernetes",
            "run",
            "--namespace",
            "test-ns",
            "--reuse-namespace",
            "--scenario",
            "scenario.json",
            "--btc-node-arg=-blocksxor=0",
            "--download-btc-data",
            "btc-data",
            "--download-path",
            "custom-node:/custom/data/",
            "--joinmarket-descriptor-regtest-fallback",
        ],
        dispatcher=dispatch,
    )

    assert exit_code == 7
    args = dispatch.call_args.args[0]
    assert args.engine == "joinmarket"
    assert args.driver == "kubernetes"
    assert args.command == "run"
    assert args.namespace == "test-ns"
    assert args.reuse_namespace
    assert args.scenario == "scenario.json"
    assert args.btc_node_arg == ["-blocksxor=0"]
    assert args.download_btc_data == "btc-data"
    assert args.download_path == "custom-node:/custom/data/"
    assert args.joinmarket_descriptor_regtest_fallback


def test_main_uses_default_download_path() -> None:
    dispatch = Mock(return_value=0)

    exit_code = cli.main(["run"], dispatcher=dispatch)

    assert exit_code == 0
    args = dispatch.call_args.args[0]
    assert args.download_path == DEFAULT_BTC_DOWNLOAD_PATH
    assert not args.joinmarket_descriptor_regtest_fallback


def test_dispatch_genscen_delegates_to_genscen_handler() -> None:
    args = command_args("genscen")
    handler = Mock()

    exit_code = cli.dispatch(args, genscen_handler=handler)

    assert exit_code == 0
    handler.assert_called_once_with(args)


def test_dispatch_clean_creates_driver_and_runs_cleanup_only() -> None:
    args = command_args("clean", image_prefix="prefix/")
    driver = Mock()
    create_driver = Mock(return_value=driver)
    create_engine = Mock()

    exit_code = cli.dispatch(
        args,
        driver_factory=create_driver,
        engine_factory=create_engine,
    )

    assert exit_code == 0
    create_driver.assert_called_once_with(args)
    create_engine.assert_not_called()
    driver.cleanup.assert_called_once_with("prefix/")


def test_dispatch_build_loads_scenario_and_prepares_images() -> None:
    args = command_args("build")
    driver = Mock()
    engine = Mock()
    create_driver = Mock(return_value=driver)
    create_engine = Mock(return_value=engine)

    exit_code = cli.dispatch(
        args,
        driver_factory=create_driver,
        engine_factory=create_engine,
    )

    assert exit_code == 0
    engine.load_scenario.assert_called_once_with()
    engine.prepare_images.assert_called_once_with()


def test_dispatch_run_loads_scenario_and_runs_engine() -> None:
    args = command_args("run")
    driver = Mock()
    engine = Mock()
    create_driver = Mock(return_value=driver)
    create_engine = Mock(return_value=engine)
    run_engine = Mock(return_value=9)

    exit_code = cli.dispatch(
        args,
        driver_factory=create_driver,
        engine_factory=create_engine,
        engine_runner=run_engine,
    )

    assert exit_code == 9
    engine.load_scenario.assert_called_once_with()
    run_engine.assert_called_once_with(args, driver, engine)


def test_dispatch_returns_failure_when_driver_is_unknown() -> None:
    args = command_args("run")
    create_driver = Mock(side_effect=ValueError("bad driver"))

    exit_code = cli.dispatch(args, driver_factory=create_driver)

    assert exit_code == 1
