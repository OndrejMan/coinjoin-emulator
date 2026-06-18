from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

from manager.application import DEFAULT_BTC_DOWNLOAD_PATH, run_engine
from manager.commands import genscen
from manager.driver import Driver
from manager.driver.docker import DockerDriver
from manager.driver.kubernetes import KubernetesDriver
from manager.driver.podman import PodmanDriver
from manager.engine.engine_base import EngineBase
from manager.engine.joinmarket_engine import JoinmarketEngine
from manager.engine.wasabi_engine import WasabiEngine

DEFAULT_IMAGE_PREFIX = ""

ParsedArgs = argparse.Namespace | SimpleNamespace
DriverFactory = Callable[[ParsedArgs], Driver]
EngineFactory = Callable[[ParsedArgs, Driver], EngineBase]
EngineRunner = Callable[[ParsedArgs, Driver, EngineBase], int]
GenscenHandler = Callable[[ParsedArgs], None]
Dispatcher = Callable[[ParsedArgs], int]


def handle_genscen(args: ParsedArgs) -> None:
    genscen.handler(cast(argparse.Namespace, args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run coinjoin simulation setup")
    subparsers = parser.add_subparsers(dest="command", title="command")

    _add_global_arguments(parser)
    _add_console_parser(subparsers)
    _add_build_parser(subparsers)
    _add_run_parser(subparsers)
    _add_clean_parser(subparsers)
    _add_genscen_parser(subparsers)

    return parser


def _add_global_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--engine",
        type=str,
        choices=["wasabi", "joinmarket"],
        default="wasabi",
    )
    parser.add_argument(
        "--driver",
        type=str,
        choices=["docker", "podman", "kubernetes"],
        default="docker",
    )
    parser.add_argument("--no-logs", action="store_true", default=False)


def _add_console_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    console_subparser = subparsers.add_parser("console", help="run console")
    _add_runtime_arguments(console_subparser)


def _add_build_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    build_subparser = subparsers.add_parser("build", help="build images")
    _add_image_build_arguments(build_subparser)
    build_subparser.add_argument("--namespace", type=str, default="coinjoin")
    build_subparser.add_argument(
        "--image-prefix", type=str, default=DEFAULT_IMAGE_PREFIX, help="image prefix"
    )


def _add_run_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run_subparser = subparsers.add_parser("run", help="run simulation")
    _add_runtime_arguments(run_subparser)
    run_subparser.add_argument(
        "--scenario", type=str, help="scenario specification file"
    )
    run_subparser.add_argument(
        "--btcFolder", type=str, help="folder with btc node data", default=""
    )
    run_subparser.add_argument(
        "--btc-node-arg",
        action="append",
        default=[],
        help="extra argument passed to btc-node run.sh/bitcoind; repeat for multiple arguments",
    )
    run_subparser.add_argument(
        "--wasabi-backend-ip",
        type=str,
        help="override wasabi-backend ip",
        default="",
    )
    run_subparser.add_argument(
        "--download-btc-data",
        type=str,
        default="",
        help="Download raw btc-node blockchain data to this path before cleanup (for Kubernetes workflow)",
    )
    run_subparser.add_argument(
        "--download-path",
        type=str,
        default=DEFAULT_BTC_DOWNLOAD_PATH,
        help=(
            "Container or pod source path to download before cleanup, in "
            "'name:/path' format"
        ),
    )


def _add_clean_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    clean_subparser = subparsers.add_parser("clean", help="clean up")
    clean_subparser.add_argument("--namespace", type=str, default="coinjoin")
    clean_subparser.add_argument(
        "--reuse-namespace", action="store_true", default=False
    )
    clean_subparser.add_argument("--proxy", type=str, default="")
    clean_subparser.add_argument(
        "--image-prefix", type=str, default=DEFAULT_IMAGE_PREFIX, help="image prefix"
    )


def _add_genscen_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    genscen_subparser = subparsers.add_parser("genscen", help="generate scenario file")
    genscen.setup_parser(genscen_subparser)


def _add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    _add_image_build_arguments(parser)
    parser.add_argument("--namespace", type=str, default="coinjoin")
    parser.add_argument(
        "--image-prefix", type=str, default=DEFAULT_IMAGE_PREFIX, help="image prefix"
    )
    parser.add_argument("--proxy", type=str, default="")
    parser.add_argument(
        "--btc-node-ip", type=str, help="override btc-node ip", default=""
    )
    parser.add_argument(
        "--control-ip", type=str, help="control ip", default="localhost"
    )
    parser.add_argument(
        "--joinmarket-descriptor-regtest-fallback",
        dest="joinmarket_descriptor_regtest_fallback",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "allow JoinMarket regtest containers to get mining addresses from "
            "Bitcoin Core's funding wallet when their descriptor RPC wallet has no keys"
        ),
    )
    parser.add_argument("--reuse-namespace", action="store_true", default=False)


def _add_image_build_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )


def create_driver(args: ParsedArgs) -> Driver:
    match args.driver:
        case "docker":
            return DockerDriver(args.namespace)
        case "podman":
            return PodmanDriver(args.namespace)
        case "kubernetes":
            return KubernetesDriver(args.namespace, args.reuse_namespace)
        case _:
            raise ValueError(f"Unknown driver '{args.driver}'")


def create_engine(args: ParsedArgs, driver: Driver) -> EngineBase:
    match args.engine:
        case "joinmarket":
            return JoinmarketEngine(args, driver)
        case "wasabi":
            return WasabiEngine(args, driver)
        case _:
            raise ValueError(f"Unknown engine '{args.engine}'")


def dispatch(
    args: ParsedArgs,
    driver_factory: DriverFactory = create_driver,
    engine_factory: EngineFactory = create_engine,
    engine_runner: EngineRunner = run_engine,
    genscen_handler: GenscenHandler = handle_genscen,
) -> int:
    if args.command == "genscen":
        genscen_handler(args)
        return 0

    try:
        driver = driver_factory(args)
    except ValueError as error:
        print(error)
        return 1

    if args.command == "clean":
        driver.cleanup(args.image_prefix)
        return 0

    try:
        engine = engine_factory(args, driver)
    except ValueError as error:
        print(error)
        return 1

    engine.load_scenario()

    match args.command:
        case "build":
            engine.prepare_images()
            return 0
        case "run":
            return engine_runner(args, driver, engine)
        case _:
            print(f"Unknown command '{args.command}'")
            return 1


def main(argv: list[str] | None = None, dispatcher: Dispatcher = dispatch) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return dispatcher(args)


if __name__ == "__main__":
    sys.exit(main())
