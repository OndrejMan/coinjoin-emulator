import subprocess
import sys
from threading import Event, Timer
from types import SimpleNamespace

import scenario_runner
from manager import process_output


class CoordinatedStream:
    """A stream that emits its line only after the other stream is read."""

    def __init__(self, line: str, started: Event, other_started: Event) -> None:
        self.line = line
        self.started = started
        self.other_started = other_started
        self.finished = False

    def readline(self) -> str:
        if self.finished:
            return ""

        self.started.set()
        if not self.other_started.wait(timeout=1):
            return "streams were not read concurrently\n"

        self.finished = True
        return self.line

    def close(self) -> None:
        pass


def test_run_scenario_streams_and_labels_stdout_and_stderr_concurrently(
    monkeypatch, capsys
) -> None:
    stdout_started = Event()
    stderr_started = Event()
    process = SimpleNamespace(
        stdout=CoordinatedStream("normal output\n", stdout_started, stderr_started),
        stderr=CoordinatedStream("error output\n", stderr_started, stdout_started),
        wait=lambda: 0,
    )
    popen_kwargs = {}

    def popen(_cmd, **kwargs):
        popen_kwargs.update(kwargs)
        return process

    monkeypatch.setattr(scenario_runner.subprocess, "Popen", popen)

    runner = object.__new__(scenario_runner.ScenarioRunner)
    runner.current_scenario_file = None
    runner.in_cluster = False
    runner.proxy = None
    runner.engine = "joinmarket"
    runner.namespace = "coinjoin"
    runner.image_prefix = ""
    runner.distributor_startup_timeout = None
    runner.current_process = None

    success, _duration = runner.run_scenario("scenario.json")

    output = capsys.readouterr().out
    assert success
    assert popen_kwargs["stdout"] is scenario_runner.subprocess.PIPE
    assert popen_kwargs["stderr"] is scenario_runner.subprocess.PIPE
    assert "[STDOUT] normal output" in output
    assert "[STDERR] error output" in output


def test_stream_process_output_drains_a_real_full_stderr_pipe(monkeypatch) -> None:
    stderr_line_count = 20_000
    child_script = (
        "import sys\n"
        "payload = 'x' * 240\n"
        f"for index in range({stderr_line_count}):\n"
        "    sys.stderr.write(f'error-{index}:{payload}\\n')\n"
        "sys.stderr.flush()\n"
        "print('stdout-finished', flush=True)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    seen_stderr_lines = 0
    seen_stdout_lines = []

    def record_output(line: str) -> None:
        nonlocal seen_stderr_lines
        if line.startswith("  [STDERR]"):
            seen_stderr_lines += 1
        elif line.startswith("  [STDOUT]"):
            seen_stdout_lines.append(line)

    monkeypatch.setattr(process_output, "print", record_output, raising=False)

    watchdog = Timer(5, process.kill)
    watchdog.start()
    try:
        process_output.stream_process_output(process)
        return_code = process.wait(timeout=1)
    finally:
        watchdog.cancel()

    assert return_code == 0
    assert seen_stderr_lines == stderr_line_count
    assert seen_stdout_lines == ["  [STDOUT] stdout-finished"]
