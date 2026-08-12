from __future__ import annotations

import builtins
import os
import sys
from datetime import datetime
from typing import TextIO
from zoneinfo import ZoneInfo

ORIGINAL_PRINT = builtins.print
PRAGUE_TZ = ZoneInfo("Europe/Prague")

LEVEL_COLORS = {
    "DEBUG": "\033[2m",
    "INFO": "\033[36m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
}
RESET_COLOR = "\033[0m"

ERROR_MARKERS = (
    "error",
    "exception",
    "failed",
    "failure",
    "invalid",
    "unknown command",
)
WARNING_MARKERS = (
    "cannot",
    "could not",
    "not initialized",
    "not running",
    "skipping",
    "timeout",
    "timed out",
)


def install_structured_print_logger() -> None:
    builtins.print = structured_print  # type: ignore[assignment]  # builtins.print is typed as an overload.


def debug(message: object, *, end: str = "\n", flush: bool = False) -> None:
    log("DEBUG", message, end=end, flush=flush)


def info(message: object, *, end: str = "\n", flush: bool = False) -> None:
    log("INFO", message, end=end, flush=flush)


def warning(message: object, *, end: str = "\n", flush: bool = False) -> None:
    log("WARNING", message, stream=sys.stderr, end=end, flush=flush)


def error(message: object, *, end: str = "\n", flush: bool = False) -> None:
    log("ERROR", message, stream=sys.stderr, end=end, flush=flush)


def blank_line(*, stream: TextIO | None = None, flush: bool = False) -> None:
    target = stream or sys.stdout
    target.write("\n")
    if flush:
        target.flush()


def log(
    level: str,
    message: object,
    *,
    stream: TextIO | None = None,
    end: str = "\n",
    flush: bool = False,
) -> None:
    target = stream or sys.stdout
    formatted = _format_message(level, str(message), target)
    target.write(f"{formatted}{end}")
    if flush:
        target.flush()


def structured_print(
    *values: object,
    sep: str = " ",
    end: str = "\n",
    file: TextIO | None = None,
    flush: bool = False,
) -> None:
    stream = file or sys.stdout
    message = sep.join(str(value) for value in values)

    if message == "":
        stream.write(end)
        if flush:
            stream.flush()
        return

    level = _infer_level(message, stream)
    formatted = _format_message(level, message, stream)
    stream.write(f"{formatted}{end}")

    if flush:
        stream.flush()


def _infer_level(message: str, stream: TextIO) -> str:
    normalized = message.strip().lower()

    if normalized.startswith("debug"):
        return "DEBUG"
    if normalized.startswith(("warning", "warn")):
        return "WARNING"
    if normalized.startswith(("error", "fatal")):
        return "ERROR"
    if stream is sys.stderr:
        return "ERROR"
    if any(marker in normalized for marker in ERROR_MARKERS):
        return "ERROR"
    if any(marker in normalized for marker in WARNING_MARKERS):
        return "WARNING"
    return "INFO"


def _format_message(level: str, message: str, stream: TextIO) -> str:
    timestamp = datetime.now(PRAGUE_TZ).strftime("%H:%M:%S")
    prefix = f"{level} | {timestamp} |"
    if _should_color(stream):
        color = LEVEL_COLORS[level]
        prefix = f"{color}{prefix}{RESET_COLOR}"
    return f"{prefix} {message}"


def _should_color(stream: TextIO) -> bool:
    color_mode = os.environ.get("COINJOIN_LOG_COLOR", "auto").lower()
    if color_mode in {"0", "false", "never", "no"}:
        return False
    if color_mode in {"1", "true", "always", "yes"}:
        return True
    if os.environ.get("NO_COLOR"):
        return False
    return stream.isatty()
