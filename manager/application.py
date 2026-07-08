import os
from collections.abc import Callable
from traceback import print_exception
from typing import Protocol

from manager import log_output as log
from manager.driver import Driver
from manager.engine.engine_base import EngineBase

DEFAULT_BTC_DOWNLOAD_PATH = "btc-node:/home/bitcoin/data/"


class RunArgs(Protocol):
    no_logs: bool
    download_btc_data: str
    download_path: str
    image_prefix: str
    controller_done_marker: str
    controller_failed_marker: str


def write_controller_marker(path: str) -> None:
    if not path:
        return
    marker = os.path.abspath(path)
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as stream:
        stream.write("done\n")


def parse_download_path(download_path: str) -> tuple[str, str]:
    if ":" not in download_path:
        raise ValueError("download path must use '<container-or-pod>:<source-path>' format")
    name, src_path = download_path.split(":", 1)
    if not name or not src_path:
        raise ValueError("download path must include both container/pod name and source path")
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
    log.info(f"Downloading {download_path} to {dest_path}")
    try:
        driver.download(name, src_path, dest_path)
        log.info(f"- {download_path} downloaded to {dest_path}")
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        log.error(f"- failed to download {download_path}: {e}")
        raise


def _finalize_controller_marker(exit_code: int, done_marker: str, failed_marker: str) -> int:
    marker = done_marker if exit_code == 0 else failed_marker
    try:
        write_controller_marker(marker)
    except OSError as error:
        log.error(f"- failed to write controller marker {marker}: {error}")
        if exit_code == 0:
            try:
                write_controller_marker(failed_marker)
            except OSError as failed_error:
                log.error(f"- failed to write controller failure marker {failed_marker}: {failed_error}")
        exit_code = 1
    return exit_code


def run_engine(
    args: RunArgs,
    driver: Driver,
    engine: EngineBase,
    btc_data_downloader: Callable[[Driver, str, str], None] = download_btc_data,
) -> int:
    exit_code = 0
    diagnostics_required = False
    try:
        engine.run()
    except KeyboardInterrupt:
        log.blank_line()
        log.warning("KeyboardInterrupt received")
        exit_code = 130
        diagnostics_required = True
    except Exception as e:  # pylint: disable=broad-exception-caught
        log.error(f"Terminating exception: {e}")
        print_exception(e)
        exit_code = 1
        diagnostics_required = True
    finally:
        try:
            if diagnostics_required:
                try:
                    diagnostics = driver.diagnostics()
                    if diagnostics:
                        log.error(diagnostics)
                except Exception as error:  # pylint: disable=broad-exception-caught
                    log.error(f"- failed to collect driver diagnostics: {error}")
            engine.stop_coinjoins()
            if not args.no_logs and engine.node is not None:
                try:
                    engine.store_logs()
                except Exception as e:  # pylint: disable=broad-exception-caught
                    log.error(f"- failed to store logs: {e}")
                    print_exception(e)
                    exit_code = 1
            elif not args.no_logs:
                log.warning("- skipping log storage: Bitcoin node is not initialized")
            if args.download_btc_data:
                try:
                    btc_data_downloader(driver, args.download_btc_data, args.download_path)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    log.error(f"- failed to download btc data: {e}")
                    print_exception(e)
                    exit_code = 1
        finally:
            try:
                driver.cleanup(args.image_prefix)
            except Exception as e:  # pylint: disable=broad-exception-caught
                log.error(f"- failed to cleanup driver resources: {e}")
                print_exception(e)
                exit_code = 1

    done_marker = getattr(args, "controller_done_marker", "")
    failed_marker = getattr(args, "controller_failed_marker", "")
    return _finalize_controller_marker(exit_code, done_marker, failed_marker)
