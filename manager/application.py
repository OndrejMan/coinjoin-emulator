"""Failure-safe application lifecycle for a single emulator run."""

import os
from collections.abc import Callable
from traceback import print_exception
from typing import Protocol

from manager import log_output as log
from manager.driver import Driver
from manager.engine.engine_base import EngineBase

DEFAULT_BTC_DOWNLOAD_PATH = "btc-node:/home/bitcoin/data/"


class RunArgs(Protocol):
    """The run options consumed by the application lifecycle."""

    no_logs: bool
    download_btc_data: str
    download_path: str
    image_prefix: str
    controller_done_marker: str
    controller_failed_marker: str


def write_controller_marker(path: str) -> None:
    """Write a completion marker, creating its parent directory if necessary."""
    if not path:
        return
    marker = os.path.abspath(path)
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as stream:
        stream.write("done\n")


def parse_download_path(download_path: str) -> tuple[str, str]:
    """Split a ``container-or-pod:/source/path`` download specification."""
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
    """Download raw Bitcoin data before the driver removes the resources."""
    name, src_path = parse_download_path(download_path)
    os.makedirs(dest_path, exist_ok=True)
    log.info(f"Downloading {download_path} to {dest_path}")
    try:
        driver.download(name, src_path, dest_path)
        log.info(f"- {download_path} downloaded to {dest_path}")
    except (RuntimeError, OSError, ValueError, TypeError) as error:
        log.error(f"- failed to download {download_path}: {error}")
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


def _system_exit_code(error: SystemExit) -> int:
    """Treat an exit from an active engine as a failed, cleaned-up run."""
    if isinstance(error.code, int) and error.code > 0:
        return error.code
    return 1


def _collect_diagnostics(driver: Driver) -> None:
    diagnostics = getattr(driver, "diagnostics", None)
    if not callable(diagnostics):
        return
    try:
        result = diagnostics()
        if result:
            log.error(result)
    except BaseException as error:  # Cleanup must not suppress final cleanup or markers.
        log.error(f"- failed to collect driver diagnostics: {error}")


def _run_cleanup(
    args: RunArgs,
    driver: Driver,
    engine: EngineBase,
    diagnostics_required: bool,
    btc_data_downloader: Callable[[Driver, str, str], None],
) -> int:
    """Run every cleanup action even if an earlier action fails."""
    exit_code = 0
    if diagnostics_required:
        _collect_diagnostics(driver)
    try:
        engine.stop_coinjoins()
    except BaseException as error:  # A failed stop must not skip artifacts or resource cleanup.
        log.error(f"- failed to stop coinjoins: {error}")
        print_exception(error)
        exit_code = 1
    try:
        engine.shutdown_engine()
    except BaseException as error:  # Async session cleanup must not skip artifacts.
        log.error(f"- failed to shut down engine resources: {error}")
        print_exception(error)
        exit_code = 1
    if not args.no_logs and engine.node is not None:
        try:
            engine.store_logs()
        except BaseException as error:
            log.error(f"- failed to store logs: {error}")
            print_exception(error)
            exit_code = 1
    elif not args.no_logs:
        log.warning("- skipping log storage: Bitcoin node is not initialized")
    if args.download_btc_data:
        try:
            btc_data_downloader(driver, args.download_btc_data, args.download_path)
        except BaseException as error:
            log.error(f"- failed to download btc data: {error}")
            print_exception(error)
            exit_code = 1
    try:
        driver.cleanup(args.image_prefix)
    except BaseException as error:
        log.error(f"- failed to cleanup driver resources: {error}")
        print_exception(error)
        exit_code = 1
    return exit_code


def run_engine(
    args: RunArgs,
    driver: Driver,
    engine: EngineBase,
    btc_data_downloader: Callable[[Driver, str, str], None] = download_btc_data,
) -> int:
    """Run an engine and always collect artifacts, clean resources, and mark the outcome."""
    exit_code = 0
    diagnostics_required = False
    try:
        engine.run()
    except KeyboardInterrupt:
        log.blank_line()
        log.warning("KeyboardInterrupt received")
        exit_code = 130
        diagnostics_required = True
    except SystemExit as error:
        log.warning("SystemExit received; proceeding to cleanup")
        exit_code = _system_exit_code(error)
        diagnostics_required = True
    except Exception as error:  # pylint: disable=broad-exception-caught
        log.error(f"Terminating exception: {error}")
        print_exception(error)
        exit_code = 1
        diagnostics_required = True

    cleanup_code = _run_cleanup(
        args, driver, engine, diagnostics_required, btc_data_downloader
    )
    if cleanup_code:
        exit_code = 1
    return _finalize_controller_marker(
        exit_code,
        getattr(args, "controller_done_marker", ""),
        getattr(args, "controller_failed_marker", ""),
    )
