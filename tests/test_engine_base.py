import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from manager.engine.configuration import ScenarioConfig, WalletConfig
from manager.engine.engine_base import EngineBase


class MinimalEngine(EngineBase):
    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig(name="test", rounds=0, blocks=0, default_version="test", wallets=[])

    def prepare_images(self) -> None:
        pass

    def start_engine_infrastructure(self) -> None:
        pass

    def start_distributor(self) -> None:
        pass

    def init_client(self) -> object:
        pass

    def start_client(self, idx: int, wallet: WalletConfig | None = None) -> None:
        return None

    def stop_client(self, idx: int) -> None:
        pass

    def store_engine_logs(self, data_path: str) -> None:
        pass

    def run_engine(self) -> None:
        pass


class EngineBaseTest(unittest.TestCase):
    def test_failed_invoice_payment_remains_pending(self) -> None:
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
