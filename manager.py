import signal
import sys
from types import SimpleNamespace

from manager.application import _finalize_controller_marker
from manager.cli import main
from manager.cli import run_id as _run_id
from manager.log_output import install_structured_print_logger

# Compatibility surface for callers that imported validation helpers from the
# historical single-file entrypoint. Runtime state lives in manager.cli.
args: SimpleNamespace | None = None


def finalize_controller_marker(exit_code: int) -> int:
    """Finalize legacy controller marker requests through the application layer."""
    return _finalize_controller_marker(
        exit_code,
        getattr(args, "controller_done_marker", ""),
        getattr(args, "controller_failed_marker", ""),
    )


def run_id(value: str) -> str:
    """Validate a run ID through the modular CLI compatibility surface."""
    return _run_id(value)


def handle_shutdown_signal(signum: int, _frame: object) -> None:
    """Turn shutdown signals into a non-zero exit so the run lifecycle can clean up."""
    signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    print(f"\n[manager.py] Received {signal_name}, triggering cleanup...", flush=True)
    raise SystemExit(128 + signum)


def install_shutdown_handlers() -> None:
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)


if __name__ == "__main__":
    install_structured_print_logger()
    install_shutdown_handlers()
    sys.exit(main())
