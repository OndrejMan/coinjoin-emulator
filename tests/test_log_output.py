import io
import re
import sys

from manager.log_output import structured_print


def test_structured_print_formats_info_with_prague_time() -> None:
    stream = io.StringIO()

    structured_print("Starting infrastructure", file=stream)

    assert re.fullmatch(
        r"INFO \| \d{2}:\d{2}:\d{2} \| Starting infrastructure\n",
        stream.getvalue(),
    )


def test_structured_print_marks_stderr_as_error() -> None:
    stream = io.StringIO()

    structured_print("Terminating exception: boom", file=stream)

    assert re.fullmatch(
        r"ERROR \| \d{2}:\d{2}:\d{2} \| Terminating exception: boom\n",
        stream.getvalue(),
    )


def test_structured_print_can_force_color(monkeypatch) -> None:
    stream = io.StringIO()
    monkeypatch.setenv("COINJOIN_LOG_COLOR", "always")

    structured_print("could not get blocks", file=stream)

    assert re.fullmatch(
        r"\033\[33mWARNING \| \d{2}:\d{2}:\d{2} \|\033\[0m could not get blocks\n",
        stream.getvalue(),
    )


def test_structured_print_uses_stderr_as_error() -> None:
    stream = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = stream
    try:
        structured_print("plain stderr message", file=sys.stderr)
    finally:
        sys.stderr = original_stderr

    assert re.fullmatch(
        r"ERROR \| \d{2}:\d{2}:\d{2} \| plain stderr message\n",
        stream.getvalue(),
    )
