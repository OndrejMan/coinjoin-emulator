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
from manager.engine.wasabi_engine import DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT, WasabiEngine
from manager.run_timezone import DEFAULT_RUN_TIMEZONE

args: argparse.Namespace | None = None
engine: EngineBase | None = None
driver: Driver | None = None
versions = set()

def handle_shutdown_signal(signum, frame):
    """Convert SIGTERM to SystemExit to ensure the cleanup phase runs"""
    signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    print(f"\n[manager.py] Received {signal_name}, triggering cleanup...", flush=True)
    raise SystemExit(128 + signum)

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
DEFAULT_BTC_DOWNLOAD_PATH = "btc-node:/home/bitcoin/data/"
DISTRIBUTOR_STARTUP_TIMEOUT_ENV = "COINJOIN_DISTRIBUTOR_STARTUP_TIMEOUT"


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
            "alphanumeric character, contain only [A-Za-z0-9._-], and must "
            "not contain '..'"
        )
    return value


def write_controller_marker(path: str) -> None:
    if not path:
        return
    marker = os.path.abspath(path)
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as stream:
        stream.write("done\n")


def finalize_controller_marker(exit_code: int) -> int:
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
    except SystemExit as e:
        # Re-raising here would skip the controller marker and lose the exit
        # code, so the shutdown is finished like any other failed run.
        print("[manager.py] SystemExit caught, proceeding to cleanup...", flush=True)
        exit_code = e.code if isinstance(e.code, int) and e.code > 0 else 1
    except Exception as e:
        print(f"Terminating exception: {e}", file=sys.stderr, flush=True)
        print_exception(e)
        exit_code = 1

    if cleanup(engine, driver, args):
        exit_code = 1
    return finalize_controller_marker(exit_code)


def download_btc_data(driver, dest_path, download_path):
    """Copy the raw Bitcoin data out before the driver removes the resources."""
    if ":" not in download_path:
        raise ValueError("download path must use '<container-or-pod>:<source-path>' format")
    name, src_path = download_path.split(":", 1)
    if not name or not src_path:
        raise ValueError("download path must include both container/pod name and source path")
    os.makedirs(dest_path, exist_ok=True)
    print(f"Downloading {download_path} to {dest_path}", flush=True)
    driver.download(name, src_path, dest_path)
    print(f"- {download_path} downloaded to {dest_path}", flush=True)


def cleanup_step(description, action):
    """Run one cleanup action; a failure must not skip the remaining ones."""
    try:
        action()
        return False
    except BaseException as e:  # pylint: disable=broad-exception-caught
        print(f"- failed to {description}: {e}", file=sys.stderr, flush=True)
        print_exception(e)
        return True


def cleanup(engine, driver, args):
    """Collect artifacts and release resources; returns True if a step failed."""
    print("[manager.py] Starting cleanup phase...", flush=True)
    failed = cleanup_step("stop coinjoins", engine.stop_coinjoins)
    failed |= cleanup_step("shut down engine resources", engine.shutdown_engine)
    if not args.no_logs:
        if engine.node is None:
            print("- skipping log storage: Bitcoin node is not initialized", flush=True)
        else:
            print("[manager.py] Storing logs...", flush=True)
            failed |= cleanup_step("store logs", engine.store_logs)
    if args.download_btc_data:
        if engine.node is None:
            print("- skipping btc data download: Bitcoin node is not initialized", flush=True)
        else:
            failed |= cleanup_step(
                "download btc data",
                lambda: download_btc_data(driver, args.download_btc_data, args.download_path),
            )
    print("[manager.py] Cleaning up resources...", flush=True)
    failed |= cleanup_step("cleanup driver resources", lambda: driver.cleanup(args.image_prefix))
    print("[manager.py] Cleanup complete", flush=True)
    return failed


def positive_seconds(value):
    """Parse a timeout in whole seconds, rejecting zero and negatives."""
    try:
        seconds = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"timeout must be an integer number of seconds: {value!r}") from error
    if seconds <= 0:
        raise argparse.ArgumentTypeError(f"timeout must be a positive number of seconds: {value!r}")
    return seconds


def default_distributor_startup_timeout():
    """Read the distributor timeout default from the environment.

    Drivers that cannot easily extend the manager command line - compose and
    the Kubernetes controller both template a fixed one - set the environment
    variable instead. An unusable value falls back to the built-in default
    rather than failing a run over a malformed knob.
    """
    raw = os.environ.get(DISTRIBUTOR_STARTUP_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT
    try:
        seconds = int(raw)
    except ValueError:
        print(f"Ignoring non-numeric {DISTRIBUTOR_STARTUP_TIMEOUT_ENV}={raw!r}", file=sys.stderr)
        return DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT
    if seconds <= 0:
        print(f"Ignoring non-positive {DISTRIBUTOR_STARTUP_TIMEOUT_ENV}={raw!r}", file=sys.stderr)
        return DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT
    return seconds


def build_parser():
    """Build the manager command line; kept out of __main__ so it can be tested."""
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
    build_subparser.add_argument("--btc-node-image", type=str, default="", help="exact btc-node image")
    build_subparser.add_argument(
        "--joinmarket-client-server-image", type=str, default="", help="exact joinmarket-client-server image"
    )
    build_subparser.add_argument("--irc-server-image", type=str, default="", help="exact irc-server image")
    build_subparser.add_argument(
        "--coinjoin-infrastructure-local-build", action="store_true", default=False,
        help="build emulator infrastructure images, including versioned Wasabi images, from local sources",
    )

    run_subparser = subparsers.add_parser("run", help="run simulation")
    run_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    run_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )
    run_subparser.add_argument("--btc-node-image", type=str, default="", help="exact btc-node image")
    run_subparser.add_argument(
        "--joinmarket-client-server-image", type=str, default="", help="exact joinmarket-client-server image"
    )
    run_subparser.add_argument("--irc-server-image", type=str, default="", help="exact irc-server image")
    run_subparser.add_argument(
        "--coinjoin-infrastructure-local-build", action="store_true", default=False,
        help="build emulator infrastructure images, including versioned Wasabi images, from local sources",
    )
    run_subparser.add_argument(
        "--scenario", type=str, help="scenario specification file"
    )
    run_subparser.add_argument(
        "--btcFolder", type=str, default="", help="host folder with existing btc-node data"
    )
    run_subparser.add_argument(
        "--btc-node-arg", action="append", default=[], help="extra bitcoind argument (repeatable)"
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
        "--download-btc-data", type=str, default="",
        help="local directory to copy the raw Bitcoin node data into before cleanup",
    )
    run_subparser.add_argument(
        "--download-path", type=str, default=DEFAULT_BTC_DOWNLOAD_PATH,
        help="'<container-or-pod>:<source-path>' to download when --download-btc-data is set",
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
    run_subparser.add_argument(
        "--distributor-startup-timeout",
        type=positive_seconds,
        default=default_distributor_startup_timeout(),
        metavar="SECONDS",
        help=(
            "how long to wait for the distributor wallet to answer before failing the run "
            f"(default {DEFAULT_DISTRIBUTOR_STARTUP_TIMEOUT}s, or ${DISTRIBUTOR_STARTUP_TIMEOUT_ENV})"
        ),
    )
    run_subparser.add_argument(
        "--disable-port-forward", action="store_true", default=False,
        help="Accepted for pipeline compatibility; the driver manages connectivity directly.",
    )
    run_subparser.add_argument("--proxy", type=str, default="")
    run_subparser.add_argument("--namespace", type=str, default="coinjoin")
    run_subparser.add_argument("--reuse-namespace", action="store_true", default=False)
    run_subparser.add_argument("--k8s-pull-secret", type=str, default=None, help="Path to Docker config.json for k8s imagePullSecret (or set K8S_PULL_SECRET env var)")

    clean_subparser = subparsers.add_parser("clean", help="clean up")
    clean_subparser.add_argument("--namespace", type=str, default="coinjoin")
    clean_subparser.add_argument(
        "--reuse-namespace", action="store_true", default=False
    )
    clean_subparser.add_argument("--proxy", type=str, default="")
    clean_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )
    clean_subparser.add_argument("--k8s-pull-secret", type=str, default=None, help="Path to Docker config.json for k8s imagePullSecret (or set K8S_PULL_SECRET env var)")

    genscen_subparser = subparsers.add_parser("genscen", help="generate scenario file")
    manager.commands.genscen.setup_parser(genscen_subparser)

    genscen_jm_subparser = subparsers.add_parser("genscen-joinmarket", help="generate JoinMarket scenario file")
    manager.commands.genscen_joinmarket.setup_parser(genscen_jm_subparser)

    return parser


if __name__ == "__main__":
    parser = build_parser()
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
            # A manager pod always runs in-cluster, whether or not the flag was passed.
            in_cluster = bool(args.in_cluster or os.environ.get("KUBERNETES_SERVICE_HOST"))
            if getattr(args, "disable_port_forward", False) and not args.proxy and not in_cluster:
                print("--disable-port-forward requires --proxy or an in-cluster manager")
                sys.exit(1)
            driver = KubernetesDriver(args.namespace,
                                      args.reuse_namespace,
                                      k8s_pull_secret,
                                      in_cluster=in_cluster,
                                      run_id=getattr(args, "run_id", None))
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
