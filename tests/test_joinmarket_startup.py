"""Exercise engine startup and the real entrypoint without containers or Core."""

import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from manager.engine import joinmarket_engine

CONTAINER = Path(__file__).resolve().parents[1] / "containers/joinmarket-client-server"


def entrypoint_arguments(directory: Path, env: dict[str, str]) -> list[str]:
    """Capture the real JoinMarket CLI arguments selected by the entrypoint."""
    directory.mkdir(parents=True)
    entrypoint = directory / "run.sh"
    entrypoint.write_text(
        (CONTAINER / "run.sh").read_text(encoding="utf-8").replace("/home/joinmarket", str(directory)),
        encoding="utf-8",
    )
    binaries = directory / "bin"
    binaries.mkdir()
    for name, source in {
        "socat": "#!/bin/sh\nexit 0\n",
        "python3": '#!/bin/sh\nprintf "%s\\n" "$@" > "$JM_TEST_CAPTURE"\n',
    }.items():
        binary = binaries / name
        binary.write_text(source, encoding="utf-8")
        binary.chmod(0o755)
    captured = directory / "daemon.cfg"
    subprocess.run(
        ["bash", str(entrypoint)],
        env={
            **os.environ,
            "MODE": "walletd",
            "JM_RPC_WALLET_FILE": "",
            **env,
            "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
            "JM_TEST_CAPTURE": str(captured),
        },
        check=True,
        capture_output=True,
        text=True,
        timeout=3,
    )
    return captured.read_text(encoding="utf-8").splitlines()


def argument_value(arguments: list[str], option: str) -> str:
    return arguments[arguments.index(option) + 1]


def test_startup_selects_created_wallets_and_a_walletless_watcher(tmp_path, monkeypatch):
    engine = object.__new__(joinmarket_engine.JoinmarketEngine)
    engine.args = SimpleNamespace(
        image_prefix="test/", proxy="", in_cluster=False, control_ip="localhost", driver="docker",
    )
    engine._core_wallet_lock = threading.Lock()  # pylint: disable=protected-access
    engine.node = Mock()
    engine.init_joinmarket_clientserver = Mock()
    monkeypatch.setattr(joinmarket_engine, "JoinMarketClientServer", Mock())
    monkeypatch.setattr(joinmarket_engine, "OrderbookWatchClient", Mock())
    monkeypatch.setattr(joinmarket_engine, "sleep", Mock())
    wallets = set()
    launches = []

    def create_wallet(name, *, disable_private_keys):
        assert disable_private_keys is True
        wallets.add(name)

    def launch(name, image, **kwargs):
        launches.append((name, kwargs["env"], set(wallets)))
        return "127.0.0.1", dict(kwargs["ports"]), None

    engine.node.create_wallet.side_effect = create_wallet
    engine.driver = Mock(run=Mock(side_effect=launch))
    engine.start_engine_infrastructure()
    engine.start_distributor()
    engine.start_client(0)
    engine.start_client(1)

    assert [name for name, _, _ in launches] == [
        "irc-server", "joinmarket-obwatch", "joinmarket-distributor", "jcs-000", "jcs-001",
    ]
    expected_wallets = {
        "joinmarket-distributor": "jm_wallet_joinmarket-distributor",
        "jcs-000": "jm_wallet_jcs-000",
        "jcs-001": "jm_wallet_jcs-001",
    }
    assert wallets == set(expected_wallets.values())
    for name, env, available_at_launch in launches:
        if name == "irc-server":
            continue
        arguments = entrypoint_arguments(tmp_path / name, env)
        if name == "joinmarket-obwatch":
            assert argument_value(arguments, "--blockchain-source") == "no-blockchain"
            assert "JM_RPC_WALLET_FILE" not in env
        else:
            assert argument_value(arguments, "--rpc-wallet-file") == expected_wallets[name]
            assert argument_value(arguments, "--rpc-wallet-file") in available_at_launch
