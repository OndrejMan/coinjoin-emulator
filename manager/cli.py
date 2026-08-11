"""Command-line parsing and command dispatch for the emulator."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from manager import log_output as log
from manager.application import DEFAULT_BTC_DOWNLOAD_PATH, run_engine
from manager.commands import genscen, genscen_joinmarket
from manager.driver import Driver
from manager.driver.docker import DockerDriver
from manager.driver.kubernetes import KubernetesDriver
from manager.driver.openshift import OpenshiftDriver
from manager.driver.podman import PodmanDriver
from manager.engine.engine_base import EngineBase
from manager.engine.joinmarket_engine import JoinmarketEngine
from manager.engine.wasabi_engine import WasabiEngine
from manager.run_timezone import DEFAULT_RUN_TIMEZONE

DEFAULT_IMAGE_PREFIX = ""
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")

ParsedArgs = argparse.Namespace | SimpleNamespace
DriverFactory = Callable[[ParsedArgs], Driver]
EngineFactory = Callable[[ParsedArgs, Driver], EngineBase]
EngineRunner = Callable[[ParsedArgs, Driver, EngineBase], int]
GenscenHandler = Callable[[ParsedArgs], None]
Dispatcher = Callable[[ParsedArgs], int]


def handle_genscen(args: ParsedArgs) -> None:
    genscen.handler(cast(argparse.Namespace, args))


def handle_genscen_joinmarket(args: ParsedArgs) -> None:
    genscen_joinmarket.handler(cast(argparse.Namespace, args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run coinjoin simulation setup")
    subparsers = parser.add_subparsers(dest="command", title="command")
    _add_global_arguments(parser)
    _add_build_parser(subparsers)
    _add_run_parser(subparsers)
    _add_clean_parser(subparsers)
    _add_genscen_parser(subparsers)
    return parser


def _add_global_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine", choices=["wasabi", "joinmarket"], default="wasabi")
    parser.add_argument("--driver", choices=["docker", "podman", "kubernetes", "openshift"], default="docker")
    parser.add_argument("--no-logs", action="store_true", default=False)
    parser.add_argument("--run-timezone", type=timezone_name, default=DEFAULT_RUN_TIMEZONE, metavar="IANA_ZONE")
    _add_branch_runtime_arguments(parser, defaults=True)


def _add_branch_runtime_arguments(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    default = None if defaults else argparse.SUPPRESS
    parser.add_argument("--namespace", default="coinjoin" if defaults else argparse.SUPPRESS)
    parser.add_argument("--reuse-namespace", action="store_true", default=False if defaults else argparse.SUPPRESS)
    parser.add_argument("--proxy", default="" if defaults else argparse.SUPPRESS)
    parser.add_argument("--in-cluster", action="store_true", default=False if defaults else argparse.SUPPRESS)
    parser.add_argument(
        "--k8s-pull-secret", default=default,
        help="Path to Docker config.json for k8s imagePullSecret (or K8S_PULL_SECRET).",
    )


def timezone_name(value: str) -> str:
    """Validate an IANA timezone while preserving its canonical input string."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise argparse.ArgumentTypeError(f"unknown IANA timezone: {value}") from error
    return value


def run_id(value: str) -> str:
    if len(value) > 63 or ".." in value or not RUN_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "run ID must be at most 63 characters, begin and end with an "
            "alphanumeric character, contain only [A-Za-z0-9._-], and must not contain '..'"
        )
    return value


def _add_build_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("build", help="build images")
    _add_image_build_arguments(parser)
    _add_infrastructure_image_arguments(parser)
    parser.add_argument("--image-prefix", default=DEFAULT_IMAGE_PREFIX, help="image prefix")
    _add_branch_runtime_arguments(parser, defaults=False)


def _add_run_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("run", help="run simulation")
    _add_image_build_arguments(parser)
    parser.add_argument("--image-prefix", default=DEFAULT_IMAGE_PREFIX, help="image prefix")
    parser.add_argument("--scenario", help="scenario specification file")
    parser.add_argument("--run-id", type=run_id, default=None)
    parser.add_argument("--controller-done-marker", default="")
    parser.add_argument("--controller-failed-marker", default="")
    parser.add_argument("--btcFolder", default="", help="folder with btc node data")
    parser.add_argument("--btc-node-arg", action="append", default=[])
    parser.add_argument("--btc-node-ip", default="", help="override btc-node ip")
    parser.add_argument("--wasabi-backend-ip", default="", help="override wasabi-backend ip")
    parser.add_argument("--control-ip", default="localhost", help="control ip")
    parser.add_argument("--download-btc-data", default="")
    parser.add_argument("--download-path", default=DEFAULT_BTC_DOWNLOAD_PATH)
    parser.add_argument(
        "--joinmarket-descriptor-regtest-fallback",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--disable-port-forward", action="store_true", default=False,
        help="Accepted for pipeline compatibility; this driver manages connectivity directly.",
    )
    _add_infrastructure_image_arguments(parser)
    _add_branch_runtime_arguments(parser, defaults=False)


def _add_clean_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("clean", help="clean up")
    parser.add_argument("--image-prefix", default=DEFAULT_IMAGE_PREFIX, help="image prefix")
    _add_branch_runtime_arguments(parser, defaults=False)


def _add_genscen_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("genscen", help="generate scenario file")
    genscen.setup_parser(parser)
    parser = subparsers.add_parser("genscen-joinmarket", help="generate JoinMarket scenario file")
    genscen_joinmarket.setup_parser(parser)


def _add_image_build_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--force-rebuild", action="store_true", help="force rebuild of images")


def _add_infrastructure_image_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--btc-node-image", default="")
    parser.add_argument("--joinmarket-client-server-image", default="")
    parser.add_argument("--irc-server-image", default="")
    parser.add_argument("--coinjoin-infrastructure-local-build", action="store_true", default=False)


def create_driver(args: ParsedArgs) -> Driver:
    match args.driver:
        case "docker":
            return DockerDriver(args.namespace)
        case "podman":
            return PodmanDriver()
        case "kubernetes":
            pull_secret = getattr(args, "k8s_pull_secret", None) or os.environ.get("K8S_PULL_SECRET")
            return KubernetesDriver(args.namespace, args.reuse_namespace, pull_secret, args.in_cluster)
        case "openshift":
            pull_secret = getattr(args, "k8s_pull_secret", None) or os.environ.get("K8S_PULL_SECRET")
            return OpenshiftDriver(args.namespace, args.reuse_namespace, pull_secret)
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
    genscen_joinmarket_handler: GenscenHandler = handle_genscen_joinmarket,
) -> int:
    if args.command == "genscen":
        genscen_handler(args)
        return 0
    if args.command == "genscen-joinmarket":
        genscen_joinmarket_handler(args)
        return 0
    try:
        driver = driver_factory(args)
    except ValueError as error:
        log.error(error)
        return 1
    if args.command == "clean":
        driver.cleanup(args.image_prefix)
        return 0
    try:
        engine = engine_factory(args, driver)
    except ValueError as error:
        log.error(error)
        return 1
    engine.load_scenario()
    match args.command:
        case "build":
            engine.prepare_images()
            return 0
        case "run":
            return engine_runner(args, driver, engine)
        case _:
            log.error(f"Unknown command '{args.command}'")
            return 1


def main(argv: list[str] | None = None, dispatcher: Dispatcher = dispatch) -> int:
    return dispatcher(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
