"""The manager's console output must survive into the run artifacts."""

import sys

from manager.run_log import RunLog


def logged_text(run_log: RunLog, tmp_path) -> str:
    target = tmp_path / "manager.log"
    run_log.copy_to(str(target))
    return target.read_bytes().decode("utf-8")


def test_stdout_and_stderr_are_forwarded_and_logged(tmp_path, capsys) -> None:
    run_log = RunLog().install()
    try:
        print("- started btc-node")
        print("Terminating exception: Could not start distributor", file=sys.stderr)
        text = logged_text(run_log, tmp_path)
    finally:
        run_log.close()

    captured = capsys.readouterr()
    assert captured.out == "- started btc-node\n"
    assert captured.err == "Terminating exception: Could not start distributor\n"
    assert text == captured.out + captured.err


def test_progress_output_is_copied_unchanged(tmp_path, capsys) -> None:
    run_log = RunLog().install()
    try:
        for current_round in range(3):
            print(f"- coinjoin rounds: {current_round} (block 7)", end="\r")
        print()
        print("- limit reached")
        text = logged_text(run_log, tmp_path)
    finally:
        run_log.close()

    assert text == capsys.readouterr().out
    assert text == "".join(f"- coinjoin rounds: {i} (block 7)\r" for i in range(3)) + "\n- limit reached\n"


def test_an_unfinished_line_is_included_in_the_copy(tmp_path) -> None:
    run_log = RunLog().install()
    try:
        print("- coinjoin rounds: 4 (block 12)", end="\r")
        text = logged_text(run_log, tmp_path)
    finally:
        run_log.close()

    assert text == "- coinjoin rounds: 4 (block 12)\r"


def test_output_after_a_copy_is_appended(tmp_path) -> None:
    run_log = RunLog().install()
    try:
        print("first", end="")
        assert logged_text(run_log, tmp_path) == "first"
        print(" second", file=sys.stderr)
        assert logged_text(run_log, tmp_path) == "first second\n"
    finally:
        run_log.close()


def test_closing_restores_the_original_streams() -> None:
    stdout, stderr = sys.stdout, sys.stderr
    run_log = RunLog().install()
    assert sys.stdout is not stdout
    run_log.close()

    assert sys.stdout is stdout
    assert sys.stderr is stderr
