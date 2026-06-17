from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from manager.application import DEFAULT_BTC_DOWNLOAD_PATH, run_engine


def test_run_skips_log_storage_when_btc_node_never_initialized(
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = Mock()
    engine.node = None
    engine.run.side_effect = RuntimeError("startup failed")
    args = SimpleNamespace(
        no_logs=False,
        download_btc_data="",
        download_path=DEFAULT_BTC_DOWNLOAD_PATH,
        image_prefix="",
    )
    driver = Mock()

    exit_code = run_engine(args, driver, engine)

    assert exit_code == 1
    engine.stop_coinjoins.assert_called_once_with()
    engine.store_logs.assert_not_called()
    driver.cleanup.assert_called_once_with("")
    assert "skipping log storage" in capsys.readouterr().err
