"""Unpack container archives as they arrive instead of holding them in memory."""

import io
import os
import stat
import tarfile
import tempfile
from collections.abc import Generator, Iterable, Iterator
from pathlib import Path

from typing_extensions import Buffer


class ChunkReader(io.RawIOBase):
    """A sequential read-only file over an iterator of byte chunks."""

    def __init__(self, chunks: Iterable[bytes]) -> None:
        super().__init__()
        self._chunks: Iterator[bytes] = iter(chunks)
        self._buffer = memoryview(b"")
        self._offset = 0

    def readable(self) -> bool:
        return True

    def readinto(self, target: Buffer, /) -> int:
        out = memoryview(target).cast("B")
        if not out:
            return 0
        while self._offset >= len(self._buffer):
            chunk = next(self._chunks, None)
            if chunk is None:
                return 0
            self._buffer = memoryview(chunk)
            self._offset = 0
        size = min(len(out), len(self._buffer) - self._offset)
        out[:size] = self._buffer[self._offset:self._offset + size]
        self._offset += size
        return size

    def drain(self) -> None:
        """Consume the transport through EOF, including errors after the tar terminator."""
        self._buffer = memoryview(b"")
        self._offset = 0
        for _ in self._chunks:
            pass

    def close(self) -> None:
        try:
            if isinstance(self._chunks, Generator):
                self._chunks.close()
        finally:
            super().close()


def _publish_extracted(source: Path, destination: Path) -> None:
    """Merge staged files into the destination without copying their contents."""
    for entry in source.iterdir():
        target = destination / entry.name
        if entry.is_dir() and not entry.is_symlink() and target.is_dir() and not target.is_symlink():
            metadata = entry.stat()
            mode = stat.S_IMODE(metadata.st_mode)
            entry.chmod(mode | 0o700)
            target.chmod(stat.S_IMODE(target.stat().st_mode) | 0o700)
            _publish_extracted(entry, target)
            target.chmod(mode)
            os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        else:
            os.replace(entry, target)


def extract_tar_stream(chunks: Iterable[bytes], dst_path: str) -> None:
    """Stage a tar stream and publish its files after the transfer succeeds."""
    with ChunkReader(chunks) as source:
        os.makedirs(dst_path, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dst_path, prefix=".coinjoin-extract-") as staged:
            with tarfile.open(fileobj=source, mode="r|") as tar:
                tar.extractall(staged, filter="fully_trusted")
            source.drain()
            _publish_extracted(Path(staged), Path(dst_path))
