from traceback import print_exception
import os
from manager.engine.joinmarket_engine import JoinmarketEngine
from manager.engine.wasabi_engine import WasabiEngine
from manager.engine.engine_base import EngineBase
import manager.commands.genscen
import sys
import argparse


DEFAULT_IMAGE_PREFIX = "ghcr.io/ondrejman/"


args: argparse.Namespace | None = None
driver = None
engine: EngineBase | None = None
versions = set()

def download_btc_data(dest_path: str):
    """Download raw Bitcoin blockchain data from the btc-node container.
    
    This is used in the Kubernetes flow: after emulation finishes on k8s,
    the raw chain data is downloaded locally so blocksci can analyze it.
    """
    os.makedirs(dest_path, exist_ok=True)
    print(f"Downloading btc-node data to {dest_path}")
    try:
        driver.download("btc-node", "/home/bitcoin/data/", dest_path)
        print(f"- btc-node data downloaded to {dest_path}")
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        print(f"- failed to download btc-node data: {e}", file=sys.stderr)
        raise


def run():
    if engine is None:
        raise RuntimeError("Engine is not initialized")
    if args is None:
        raise RuntimeError("Arguments are not initialized")
    exit_code = 0
    try:
        engine.run()
    except KeyboardInterrupt:
        print()
        print("KeyboardInterrupt received")
        exit_code = 130
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        print(f"Terminating exception: {e}", file=sys.stderr)
        print_exception(e)
        exit_code = 1
    finally:
        engine.stop_coinjoins()
        if not args.no_logs and engine.node is not None:
            engine.store_logs()
        elif not args.no_logs:
            print("- skipping log storage: Bitcoin node is not initialized", file=sys.stderr)
        if args.download_btc_data:
            download_btc_data(args.download_btc_data)
        driver.cleanup(args.image_prefix) # todo
    if exit_code:
        sys.exit(exit_code)

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
        choices=["docker", "podman", "kubernetes"],
        default="docker",
    )
    parser.add_argument("--no-logs", action="store_true", default=False)

    console_subparser = subparsers.add_parser("console", help="run console")
    console_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    console_subparser.add_argument("--namespace", type=str, default="coinjoin")
    console_subparser.add_argument(
        "--image-prefix", type=str, default=DEFAULT_IMAGE_PREFIX, help="image prefix"
    )
    console_subparser.add_argument("--proxy", type=str, default="")
    console_subparser.add_argument(
        "--btc-node-ip", type=str, help="override btc-node ip", default=""
    )
    console_subparser.add_argument(
        "--control-ip", type=str, help="control ip", default="localhost"
    )
    console_subparser.add_argument("--reuse-namespace", action="store_true", default=False)



    build_subparser = subparsers.add_parser("build", help="build images")
    build_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    build_subparser.add_argument("--namespace", type=str, default="coinjoin")
    build_subparser.add_argument(
        "--image-prefix", type=str, default=DEFAULT_IMAGE_PREFIX, help="image prefix"
    )

    run_subparser = subparsers.add_parser("run", help="run simulation")
    run_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    run_subparser.add_argument(
        "--image-prefix", type=str, default=DEFAULT_IMAGE_PREFIX, help="image prefix"
    )
    run_subparser.add_argument(
        "--scenario", type=str, help="scenario specification file"
    )
    run_subparser.add_argument(
        "--btcFolder", type=str, help="folder with btc node data", default=""
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
    run_subparser.add_argument("--proxy", type=str, default="")
    run_subparser.add_argument("--namespace", type=str, default="coinjoin")
    run_subparser.add_argument("--reuse-namespace", action="store_true", default=False)
    run_subparser.add_argument(
        "--download-btc-data",
        type=str,
        default="",
        help="Download raw btc-node blockchain data to this path before cleanup (for Kubernetes workflow)",
    )

    clean_subparser = subparsers.add_parser("clean", help="clean up")
    clean_subparser.add_argument("--namespace", type=str, default="coinjoin")
    clean_subparser.add_argument(
        "--reuse-namespace", action="store_true", default=False
    )
    clean_subparser.add_argument("--proxy", type=str, default="")
    clean_subparser.add_argument(
        "--image-prefix", type=str, default=DEFAULT_IMAGE_PREFIX, help="image prefix"
    )

    genscen_subparser = subparsers.add_parser("genscen", help="generate scenario file")
    manager.commands.genscen.setup_parser(genscen_subparser)

    args = parser.parse_args()

    if args.command == "genscen":
        manager.commands.genscen.handler(args)
        sys.exit(0)

    match args.driver:
        case "docker":
            from manager.driver.docker import DockerDriver

            driver = DockerDriver(args.namespace)
        case "podman":
            from manager.driver.podman import PodmanDriver

            driver = PodmanDriver(args.namespace)
        case "kubernetes":
            from manager.driver.kubernetes import KubernetesDriver

            driver = KubernetesDriver(args.namespace, args.reuse_namespace)
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
            run()
        case _:
            print(f"Unknown command '{args.command}'")
            sys.exit(1)
