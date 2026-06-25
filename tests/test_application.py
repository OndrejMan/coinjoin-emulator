import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from manager.application import download_btc_data, parse_download_path, run_engine


def run_args(
    no_logs: bool = False,
    download_btc_data_path: str = "",
    download_path: str = "btc-node:/home/bitcoin/data/",
    image_prefix: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        no_logs=no_logs,
        download_btc_data=download_btc_data_path,
        download_path=download_path,
        image_prefix=image_prefix,
    )


def test_parse_download_path_splits_container_and_source_path() -> None:
    assert parse_download_path("btc-node:/home/bitcoin/data/") == (
        "btc-node",
        "/home/bitcoin/data/",
    )


@pytest.mark.parametrize("download_path", ["btc-node", ":/data", "btc-node:"])
def test_parse_download_path_rejects_invalid_paths(download_path: str) -> None:
    with pytest.raises(ValueError):
        parse_download_path(download_path)


def test_download_btc_data_creates_destination_and_downloads_node_data() -> None:
    driver = Mock()

    with tempfile.TemporaryDirectory() as temp_dir:
        dest_path = Path(temp_dir) / "btc-data"

        download_btc_data(driver, str(dest_path))

    driver.download.assert_called_once_with(
        "btc-node",
        "/home/bitcoin/data/",
        str(dest_path),
    )


def test_download_btc_data_uses_configured_source_path() -> None:
    driver = Mock()

    with tempfile.TemporaryDirectory() as temp_dir:
        dest_path = Path(temp_dir) / "btc-data"

        download_btc_data(driver, str(dest_path), "custom-node:/custom/data/")

    driver.download.assert_called_once_with(
        "custom-node",
        "/custom/data/",
        str(dest_path),
    )


def test_download_btc_data_reports_and_reraises_failures(capsys: pytest.CaptureFixture[str]) -> None:
    driver = Mock()
    driver.download.side_effect = RuntimeError("download failed")

    with tempfile.TemporaryDirectory() as temp_dir:
        with pytest.raises(RuntimeError):
            download_btc_data(driver, str(Path(temp_dir) / "btc-data"))

    assert "failed to download btc-node:/home/bitcoin/data/" in capsys.readouterr().err


def test_run_engine_stores_logs_when_node_is_initialized() -> None:
    args = run_args(image_prefix="prefix/")
    driver = Mock()
    engine = Mock()
    engine.node = Mock()

    exit_code = run_engine(args, driver, engine)

    assert exit_code == 0
    engine.run.assert_called_once_with()
    engine.stop_coinjoins.assert_called_once_with()
    engine.store_logs.assert_called_once_with()
    driver.cleanup.assert_called_once_with("prefix/")


def test_run_engine_cleans_up_when_log_storage_fails() -> None:
    args = run_args()
    driver = Mock()
    engine = Mock()
    engine.node = Mock()
    engine.store_logs.side_effect = RuntimeError("rpc unavailable")

    exit_code = run_engine(args, driver, engine)

    assert exit_code == 1
    engine.stop_coinjoins.assert_called_once_with()
    engine.store_logs.assert_called_once_with()
    driver.cleanup.assert_called_once_with("")


def test_run_engine_downloads_btc_data_before_cleanup() -> None:
    args = run_args(
        no_logs=True,
        download_btc_data_path="/tmp/btc-data",
        download_path="custom-node:/custom/data/",
    )
    driver = Mock()
    engine = Mock()
    engine.node = Mock()
    download = Mock()

    exit_code = run_engine(args, driver, engine, btc_data_downloader=download)

    assert exit_code == 0
    download.assert_called_once_with(driver, "/tmp/btc-data", "custom-node:/custom/data/")
    driver.cleanup.assert_called_once_with("")


def test_run_engine_cleans_up_when_btc_data_download_fails() -> None:
    args = run_args(no_logs=True, download_btc_data_path="/tmp/btc-data")
    driver = Mock()
    engine = Mock()
    engine.node = Mock()
    download = Mock(side_effect=RuntimeError("download failed"))

    exit_code = run_engine(args, driver, engine, btc_data_downloader=download)

    assert exit_code == 1
    download.assert_called_once_with(driver, "/tmp/btc-data", "btc-node:/home/bitcoin/data/")
    driver.cleanup.assert_called_once_with("")


def test_run_engine_returns_keyboard_interrupt_exit_code() -> None:
    args = run_args(no_logs=True)
    driver = Mock()
    engine = Mock()
    engine.node = None
    engine.run.side_effect = KeyboardInterrupt

    exit_code = run_engine(args, driver, engine)

    assert exit_code == 130
    engine.stop_coinjoins.assert_called_once_with()
    driver.cleanup.assert_called_once_with("")
