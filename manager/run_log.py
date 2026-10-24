"""Keep a copy of the manager's console output for the run artifacts.

On Kubernetes the manager's stdout lives only in the controller pod's log, so a
run that fails during setup leaves artifacts that cannot say which step failed.
"""

import shutil
import sys
import tempfile
import threading
from typing import TextIO


class RunLog:
    """Copy stdout and stderr unchanged while installed."""

    def __init__(self) -> None:
        self._file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="")
        self._lock = threading.Lock()
        self._originals: tuple[TextIO, TextIO] | None = None

    def install(self) -> "RunLog":
        self._originals = (sys.stdout, sys.stderr)
        sys.stdout = _Tee(sys.stdout, self._file, self._lock)
        sys.stderr = _Tee(sys.stderr, self._file, self._lock)
        return self

    def close(self) -> None:
        if self._originals is not None:
            sys.stdout, sys.stderr = self._originals
            self._originals = None
        self._file.close()

    def copy_to(self, path: str) -> None:
        """Write the output captured so far to path."""
        with self._lock, open(path, "w", encoding="utf-8", newline="") as target:
            self._file.flush()
            self._file.seek(0)
            try:
                shutil.copyfileobj(self._file, target)
            finally:
                self._file.seek(0, 2)


class _Tee:
    """Write to both the original stream and the shared log."""

    def __init__(self, stream: TextIO, log: TextIO, lock: threading.Lock) -> None:
        self._stream = stream
        self._log = log
        self._lock = lock

    def write(self, text: str) -> int:
        with self._lock:
            written = self._stream.write(text)
            self._log.write(text)
            return written

    def flush(self) -> None:
        with self._lock:
            self._stream.flush()
            self._log.flush()

    def __getattr__(self, name: str) -> object:
        return getattr(self._stream, name)
