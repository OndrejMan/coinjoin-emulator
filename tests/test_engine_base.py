import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from manager.engine.engine_base import EngineBase


class MinimalEngine(EngineBase):
    def default_scenario(self):
        return None

    def prepare_images(self):
        pass

    def start_engine_infrastructure(self):
        pass

    def start_distributor(self):
        pass

    def init_client(self):
        pass

    def start_client(self, idx: int, wallet=None):
        pass

    def stop_client(self, idx: int):
        pass

    def store_engine_logs(self, data_path):
        pass

    def run_engine(self):
        pass


class EngineBaseTest(unittest.TestCase):
    def test_failed_invoice_payment_remains_pending(self):
        engine = MinimalEngine(Mock(), Mock(), "/tmp")
        engine.current_block = 0
        engine.current_round = 0
        engine.invoices = {(0, 0): [("bcrt1destination", 100000)]}
        engine.distributor = Mock()
        engine.distributor.send.side_effect = Exception("direct-send failed")

        with self.assertRaisesRegex(Exception, "Invoice payment failed"):
            engine.update_invoice_payments()

        self.assertEqual(engine.invoices, {(0, 0): [("bcrt1destination", 100000)]})


if __name__ == "__main__":
    unittest.main()
