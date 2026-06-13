import contextlib
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def load_manager_entrypoint():
    sys.modules.setdefault("numpy", types.ModuleType("numpy"))
    sys.modules.setdefault("numpy.random", types.ModuleType("numpy.random"))
    spec = importlib.util.spec_from_file_location(
        "emulator_manager_entrypoint",
        PROJECT_ROOT / "manager.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ManagerRunTest(unittest.TestCase):
    def test_run_skips_log_storage_when_btc_node_never_initialized(self):
        manager_entrypoint = load_manager_entrypoint()
        engine = Mock()
        engine.node = None
        engine.run.side_effect = RuntimeError("startup failed")
        args = SimpleNamespace(no_logs=False, download_btc_data="", image_prefix="")
        driver = Mock()

        manager_entrypoint.engine = engine
        manager_entrypoint.args = args
        manager_entrypoint.driver = driver

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exit_context:
                manager_entrypoint.run()

        self.assertEqual(exit_context.exception.code, 1)
        engine.stop_coinjoins.assert_called_once_with()
        engine.store_logs.assert_not_called()
        driver.cleanup.assert_called_once_with("")
        self.assertIn("skipping log storage", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
