import argparse
import os
import re
import signal
import sys
from traceback import print_exception
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import manager.commands.genscen
import manager.commands.genscen_joinmarket
from manager.driver import Driver
from manager.engine.engine_base import EngineBase
from manager.engine.joinmarket_engine import JoinmarketEngine
from manager.engine.wasabi_engine import WasabiEngine
from manager.run_timezone import DEFAULT_RUN_TIMEZONE

args: argparse.Namespace | None = None
engine: EngineBase | None = None
driver: Driver | None = None
versions = set()

def handle_shutdown_signal(signum, _frame):
    """Convert SIGTERM to SystemExit to ensure finally block runs"""
    signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    print(f"\n[manager.py] Received {signal_name}, triggering cleanup...", flush=True)
    # Raise SystemExit which will trigger the finally block
    sys.exit(1)

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


def timezone_name(value):
    """Validate an IANA timezone while preserving its canonical input string."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise argparse.ArgumentTypeError(f"unknown IANA timezone: {value}") from error
    return value


def run_id(value):
    if len(value) > 63 or ".." in value or not RUN_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "run ID must be at most 63 characters, begin and end with an "
            "alphanumeric character, contain only [A-Za-z0-9._-], and must "
            "not contain '..'"
        )
    return value


def write_controller_marker(path):
    if not path:
        return
    marker = os.path.abspath(path)
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as stream:
        stream.write("done\n")


def finalize_controller_marker(exit_code):
    done_marker = getattr(args, "controller_done_marker", "")
    failed_marker = getattr(args, "controller_failed_marker", "")
    marker = done_marker if exit_code == 0 else failed_marker
    try:
        write_controller_marker(marker)
    except OSError as error:
        print(f"- failed to write controller marker {marker}: {error}", file=sys.stderr, flush=True)
        if exit_code == 0:
            try:
                write_controller_marker(failed_marker)
            except OSError as failed_error:
                print(
                    f"- failed to write controller failure marker {failed_marker}: {failed_error}",
                    file=sys.stderr,
                    flush=True,
                )
        exit_code = 1
    return exit_code


def run():
    if engine is None:
        raise RuntimeError("Engine is not initialized")
    if args is None:
        raise RuntimeError("Arguments are not initialized")
    if driver is None:
        raise RuntimeError("Driver is not initialized")

    # Register signal handlers to ensure finally block runs on SIGTERM/SIGINT
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)

    exit_code = 0
    try:
        engine.run()
    except KeyboardInterrupt:
        print()
        print("KeyboardInterrupt received", flush=True)
        exit_code = 130
    except SystemExit:
        print("[manager.py] SystemExit caught, proceeding to cleanup...", flush=True)
        raise  # Re-raise to ensure finally runs
    except Exception as e:
        print(f"Terminating exception: {e}", file=sys.stderr, flush=True)
        print_exception(e)
        exit_code = 1
    finally:
        print("[manager.py] Starting cleanup phase...", flush=True)
        engine.stop_coinjoins()
        if not args.no_logs:
            print("[manager.py] Storing logs...", flush=True)
            try:
                engine.store_logs()
            except Exception as e:
                print(f"- failed to store logs: {e}", file=sys.stderr, flush=True)
                print_exception(e)
                exit_code = 1
        print("[manager.py] Cleaning up resources...", flush=True)
        driver.cleanup(args.image_prefix)
        print("[manager.py] Cleanup complete", flush=True)

    return finalize_controller_marker(exit_code)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run coinjoin simulation setup")
    subparsers = parser.add_subparsers(dest="command", title="command")

    parser.add_argument(
        "--engine",
        type=str,
        choices=["wasabi", "joinmarket"],
        default="wasabi",
    )
    parser.add_argument(
        "--driver",
        type=str,
        choices=["docker", "podman", "kubernetes", "openshift"],
        default="docker",
    )
    parser.add_argument("--no-logs", action="store_true", default=False)
    parser.add_argument(
        "--run-timezone",
        type=timezone_name,
        default=DEFAULT_RUN_TIMEZONE,
        metavar="IANA_ZONE",
        help=f"IANA timezone used in newly created run directory names (default: {DEFAULT_RUN_TIMEZONE}).",
    )

    parser.add_argument(
        "--in-cluster",
        action="store_true",
        default=False,
        help="Running inside Kubernetes cluster (uses service account)"
    )

    build_subparser = subparsers.add_parser("build", help="build images")
    build_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    build_subparser.add_argument("--namespace", type=str, default="coinjoin")
    build_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )

    run_subparser = subparsers.add_parser("run", help="run simulation")
    run_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    run_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )
    run_subparser.add_argument(
        "--scenario", type=str, help="scenario specification file"
    )
    run_subparser.add_argument(
        "--btc-node-ip", type=str, help="override btc-node ip", default=""
    )
    run_subparser.add_argument(
        "--wasabi-backend-ip",
        type=str,
        help="override wasabi-backend ip",
        default="",
    )
    run_subparser.add_argument(
        "--control-ip", type=str, help="control ip", default="localhost"
    )
    run_subparser.add_argument(
        "--run-id",
        type=run_id,
        default=None,
        help="Deterministic output directory name instead of the timestamp/scenario name.",
    )
    run_subparser.add_argument(
        "--controller-done-marker",
        default="",
        help="Write this marker after logs and requested Bitcoin data are stored.",
    )
    run_subparser.add_argument(
        "--controller-failed-marker",
        default="",
        help="Write this marker when the emulation or artifact collection fails.",
    )
    run_subparser.add_argument("--proxy", type=str, default="")
    run_subparser.add_argument("--namespace", type=str, default="coinjoin")
    run_subparser.add_argument("--reuse-namespace", action="store_true", default=False)
    run_subparser.add_argument(
        "--k8s-pull-secret", type=str, default=None,
        help="Path to Docker config.json for k8s imagePullSecret (or set K8S_PULL_SECRET env var)",
    )

    clean_subparser = subparsers.add_parser("clean", help="clean up")
    clean_subparser.add_argument("--namespace", type=str, default="coinjoin")
    clean_subparser.add_argument(
        "--reuse-namespace", action="store_true", default=False
    )
    clean_subparser.add_argument("--proxy", type=str, default="")
    clean_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )
    clean_subparser.add_argument(
        "--k8s-pull-secret", type=str, default=None,
        help="Path to Docker config.json for k8s imagePullSecret (or set K8S_PULL_SECRET env var)",
    )

    genscen_subparser = subparsers.add_parser("genscen", help="generate scenario file")
    manager.commands.genscen.setup_parser(genscen_subparser)

    genscen_jm_subparser = subparsers.add_parser("genscen-joinmarket", help="generate JoinMarket scenario file")
    manager.commands.genscen_joinmarket.setup_parser(genscen_jm_subparser)

    args = parser.parse_args()

    if args.command == "genscen":
        manager.commands.genscen.handler(args)
        sys.exit(0)
    if args.command == "genscen-joinmarket":
        manager.commands.genscen_joinmarket.handler(args)
        sys.exit(0)

    match args.driver:
        case "docker":
            from manager.driver.docker import DockerDriver

            driver = DockerDriver(args.namespace)
        case "podman":
            from manager.driver.podman import PodmanDriver

            driver = PodmanDriver()
        case "kubernetes":
            from manager.driver.kubernetes import KubernetesDriver

            # Support for k8s image pull secret
            k8s_pull_secret = args.k8s_pull_secret or os.environ.get("K8S_PULL_SECRET")
            driver = KubernetesDriver(args.namespace,
                                      args.reuse_namespace,
                                      k8s_pull_secret,
                                      in_cluster=args.in_cluster)
        case "openshift":
            from manager.driver.openshift import OpenshiftDriver
            k8s_pull_secret = args.k8s_pull_secret or os.environ.get("K8S_PULL_SECRET")
            driver = OpenshiftDriver(args.namespace, args.reuse_namespace, k8s_pull_secret)
        case _:
            print(f"Unknown driver '{args.driver}'")
            sys.exit(1)

    match args.engine:
        case "joinmarket":
            engine = JoinmarketEngine(args, driver)
        case "wasabi":
            engine = WasabiEngine(args, driver)
        case _:
            print(f"Unknown engine '{args.engine}'")
            sys.exit(1)

    engine.load_scenario()

    match args.command:
        case "build":
            engine.prepare_images()
        case "clean":
            driver.cleanup(args.image_prefix)
        case "run":
            sys.exit(run())
        case _:
            print(f"Unknown command '{args.command}'")
            sys.exit(1)
