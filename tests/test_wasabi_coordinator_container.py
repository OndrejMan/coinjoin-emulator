from pathlib import Path


RUN_SCRIPT = Path(__file__).parents[1] / "containers" / "wasabi-coordinator" / "2.6.0" / "run.sh"


def test_coordinator_renders_regtest_config_before_single_start() -> None:
    script = RUN_SCRIPT.read_text(encoding="utf-8")
    lines = script.splitlines()
    config_write = next(index for index, line in enumerate(lines) if "coordinator/Config.json" in line and ">" in line)
    starts = [index for index, line in enumerate(lines) if "./WalletWasabi.Coordinator" in line]

    assert starts == [len(lines) - 1]
    assert config_write < starts[0]
    assert lines[starts[0]].startswith("exec ")
    assert "sleep 15" not in script
    assert ': "${WASABI_BIND:=http://0.0.0.0:37128}"' in script
