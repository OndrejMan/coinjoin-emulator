import os
import sys
from collections.abc import Callable
from traceback import print_exception
from typing import Protocol

from manager.driver import Driver
from manager.engine.engine_base import EngineBase

DEFAULT_BTC_DOWNLOAD_PATH = "btc-node:/home/bitcoin/data/"


class RunArgs(Protocol):
    no_logs: bool
    download_btc_data: str
    download_path: str
    image_prefix: str


def parse_download_path(download_path: str) -> tuple[str, str]:
    if ":" not in download_path:
        raise ValueError(
            "download path must use '<container-or-pod>:<source-path>' format"
        )
    name, src_path = download_path.split(":", 1)
    if not name or not src_path:
        raise ValueError(
            "download path must include both container/pod name and source path"
        )
    return name, src_path


def download_btc_data(
    driver: Driver,
    dest_path: str,
    download_path: str = DEFAULT_BTC_DOWNLOAD_PATH,
) -> None:
    """Download raw Bitcoin blockchain data from the btc-node container.

    This is used in the Kubernetes flow: after emulation finishes on k8s,
    the raw chain data is downloaded locally so blocksci can analyze it.
    """
    name, src_path = parse_download_path(download_path)
    os.makedirs(dest_path, exist_ok=True)
    print(f"Downloading {download_path} to {dest_path}")
    try:
        driver.download(name, src_path, dest_path)
        print(f"- {download_path} downloaded to {dest_path}")
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        print(f"- failed to download {download_path}: {e}", file=sys.stderr)
        raise


def run_engine(
    args: RunArgs,
    driver: Driver,
    engine: EngineBase,
    btc_data_downloader: Callable[[Driver, str, str], None] = download_btc_data,
) -> int:
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
            btc_data_downloader(driver, args.download_btc_data, args.download_path)
        driver.cleanup(args.image_prefix)

    return exit_code
