"""Log collection shared by every engine."""

import datetime
import json
import multiprocessing
import multiprocessing.pool
import os
import random
import shutil
from time import sleep
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from manager.btc_node import BtcNode
from manager.driver import Driver
from manager.engine.base.manifest import ProducerLabelEvidence, write_producer_label_manifest
from manager.engine.base.protocols import EmulatorClient, EngineArgs
from manager.engine.configuration import ScenarioConfig
from manager.exceptions import RpcError
from manager.run_timezone import DEFAULT_RUN_TIMEZONE


class EngineLogsMixin:
    """Writes the client, node and engine artifacts into the per-run data directory."""

    driver: Driver
    clients: list[EmulatorClient]
    node: BtcNode | None
    scenario: ScenarioConfig
    current_block: int
    log_src_path: str
    args: EngineArgs

    if TYPE_CHECKING:
        pass

    def store_client_logs(self, client: EmulatorClient, data_path: str) -> None:
        sleep(random.random() * 3)
        client_path = os.path.join(data_path, client.name)
        os.mkdir(client_path)
        with open(os.path.join(client_path, "coins.json"), "w") as f:
            json.dump(client.list_coins(), f, indent=2)
            print(f"- stored {client.name} coins")
        with open(os.path.join(client_path, "unspent_coins.json"), "w") as f:
            json.dump(client.list_unspent_coins(), f, indent=2)
            print(f"- stored {client.name} unspent coins")
        with open(os.path.join(client_path, "keys.json"), "w") as f:
            json.dump(client.list_keys(), f, indent=2)
            print(f"- stored {client.name} keys")

        # Store fidelity bonds data if available
        if hasattr(client, 'export_fidelity_bonds_data') and hasattr(client, 'fidelity_bonds'):
            bonds_data = client.export_fidelity_bonds_data(self.current_block)
            with open(os.path.join(client_path, "fidelity_bonds.json"), "w") as f:
                json.dump(bonds_data, f, indent=2)
                if bonds_data['total_bonds'] > 0:
                    print(f"- stored {client.name} fidelity bonds ({bonds_data['total_bonds']} bonds)")
                else:
                    print(f"- stored {client.name} fidelity bonds (none)")

        try:
            self.driver.download(client.name, self.log_src_path, client_path)
            print(f"- stored {client.name} logs, {self.log_src_path}, {client_path}")
        except Exception:
            print(f"- could not store {client.name} logs")

    def log_run_path(self) -> str:
        requested_run_id = getattr(self.args, "run_id", "")
        if requested_run_id:
            return f"./logs/{requested_run_id}"
        run_timezone = getattr(self.args, "run_timezone", DEFAULT_RUN_TIMEZONE)
        timestamp = datetime.datetime.now(ZoneInfo(run_timezone)).strftime("%Y-%m-%d_%H-%M")
        return f"./logs/{timestamp}_{self.scenario.name}"

    def ensure_log_run_path_available(self) -> None:
        # The pipeline launcher may pre-create the run directory to place its
        # host manifest there; only a directory that already holds emulator
        # artifacts marks a genuine earlier run.
        run_path = self.log_run_path()
        if os.path.exists(os.path.join(run_path, "coinjoin_emulator_data")):
            raise RuntimeError(f"Run log directory already exists: {run_path}")

    def store_logs(self) -> None:
        print("Storing logs")
        run_path = self.log_run_path()
        experiment_path = os.path.join(run_path, "coinjoin_emulator_data")
        data_path = os.path.join(experiment_path, "data")
        os.makedirs(data_path)

        with open(os.path.join(experiment_path, "scenario.json"), "w") as f:
            json.dump(self.scenario.to_dict(), f, indent=2)
            print("- stored scenario")

        stored_blocks = 0
        node_path = os.path.join(data_path, "btc-node")
        os.mkdir(node_path)
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        try:
            block_count = self.node.get_block_count()
        except (TypeError, RpcError) as error:
            # Only the block count is optional: without it there is nothing to export.
            print(f"Failed to get block count: {error}")
            block_count = 0
        while stored_blocks < block_count:
            block_hash = self.node.get_block_hash(stored_blocks)
            block = self.node.get_block_info(block_hash)
            with open(os.path.join(node_path, f"block_{stored_blocks}.json"), "w") as f:
                json.dump(block, f, indent=2)
            stored_blocks += 1

        print(f"- stored {stored_blocks} blocks")

        print("- storing engine logs")
        producer_label_evidence = self.store_engine_logs(data_path)
        write_producer_label_manifest(data_path, producer_label_evidence)
        print("- finished storing engine logs, stored producer-label manifest")

        print(f"- storing logs for {len(self.clients)} clients in parallel")
        with multiprocessing.pool.ThreadPool() as pool:
            pool.starmap(self.store_client_logs, [(client, data_path) for client in self.clients])

        archive_base = os.path.join(run_path, ".emulation_logs")
        archive_path = shutil.make_archive(archive_base, "zip", run_path, "coinjoin_emulator_data")
        os.replace(archive_path, os.path.join(experiment_path, "emulation_logs.zip"))
        print("- zip archive created")

    def store_engine_logs(self, data_path: str) -> ProducerLabelEvidence | None:
        """Engines override this to write their own artifacts into data_path."""
        raise NotImplementedError
