"""Container archives are unpacked from their stream without being assembled in memory."""

import io
import tarfile
from pathlib import Path

import pytest

from manager.driver.archive import ChunkReader, extract_tar_stream


def test_a_tar_stream_is_unpacked_across_chunk_boundaries(tmp_path):
    payload = io.BytesIO()
    contents = bytes(range(256)) * 64
    with tarfile.open(fileobj=payload, mode="w") as tar:
        entry = tarfile.TarInfo("data/blocks/blk00000.dat")
        entry.size = len(contents)
        tar.addfile(entry, io.BytesIO(contents))
        entry = tarfile.TarInfo("data/blocks/index/CURRENT")
        entry.size = 5
        tar.addfile(entry, io.BytesIO(b"MANIF"))
    archive = payload.getvalue()
    chunks = [archive[offset:offset + 1000] for offset in range(0, len(archive), 1000)]

    extract_tar_stream(iter(chunks), str(tmp_path))

    assert (tmp_path / "data/blocks/blk00000.dat").read_bytes() == contents
    assert (tmp_path / "data/blocks/index/CURRENT").read_bytes() == b"MANIF"


def archive_bytes() -> bytes:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as tar:
        for name, contents in [("logs/run.log", b"new log"), ("logs/large.dat", b"x" * 40_000)]:
            entry = tarfile.TarInfo(name)
            entry.size = len(contents)
            tar.addfile(entry, io.BytesIO(contents))
    return payload.getvalue()


@pytest.mark.parametrize("cutoff", [12_288, None])
def test_transport_errors_preserve_existing_files_and_close_the_stream(tmp_path, cutoff) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_bytes(b"previous log")
    closed = []

    def chunks():
        try:
            yield archive_bytes()[:cutoff]
            raise OSError("broken transfer")
        finally:
            closed.append(True)

    with pytest.raises(OSError, match="broken transfer"):
        extract_tar_stream(chunks(), str(tmp_path))

    assert (logs / "run.log").read_bytes() == b"previous log"
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == [
        Path("logs"), Path("logs/run.log"),
    ]
    assert closed == [True]


def test_invalid_tar_closes_its_source_and_removes_staging(tmp_path) -> None:
    closed = []

    def chunks():
        try:
            yield b"invalid tar" * 1000
            pytest.fail("invalid archive must stop extraction")
        finally:
            closed.append(True)

    with pytest.raises(tarfile.ReadError):
        extract_tar_stream(chunks(), str(tmp_path))

    assert closed == [True]
    assert list(tmp_path.iterdir()) == []


def test_files_are_published_only_after_transport_eof(tmp_path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_bytes(b"previous log")
    (logs / "unrelated").write_bytes(b"keep me")

    def chunks():
        yield archive_bytes()
        assert (logs / "run.log").read_bytes() == b"previous log"
        assert not (logs / "large.dat").exists()
        yield b"\0" * 512

    extract_tar_stream(chunks(), str(tmp_path))

    assert (logs / "run.log").read_bytes() == b"new log"
    assert (logs / "large.dat").read_bytes() == b"x" * 40_000
    assert (logs / "unrelated").read_bytes() == b"keep me"
    assert list(tmp_path.iterdir()) == [logs]


def test_zero_length_read_does_not_advance_the_source() -> None:
    requested = []

    def chunks():
        requested.append(True)
        yield b"abc"

    with ChunkReader(chunks()) as reader:
        assert reader.readinto(bytearray()) == 0
        assert requested == []
        assert reader.read(3) == b"abc"


@pytest.mark.parametrize("directory_mode", [0o750, 0o550])
def test_publishing_preserves_links_and_directory_metadata(tmp_path, directory_mode) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as tar:
        directory = tarfile.TarInfo("logs")
        directory.type = tarfile.DIRTYPE
        directory.mode = directory_mode
        directory.mtime = 1234567890
        tar.addfile(directory)
        entry = tarfile.TarInfo("logs/run.log")
        entry.size = 3
        tar.addfile(entry, io.BytesIO(b"log"))
        for name, kind, target in [
            ("logs/hardlink", tarfile.LNKTYPE, "logs/run.log"),
            ("logs/symlink", tarfile.SYMTYPE, "run.log"),
        ]:
            link = tarfile.TarInfo(name)
            link.type = kind
            link.linkname = target
            tar.addfile(link)

    extract_tar_stream([payload.getvalue()], str(tmp_path))

    assert (logs / "hardlink").stat().st_ino == (logs / "run.log").stat().st_ino
    assert (logs / "symlink").is_symlink()
    assert (logs / "symlink").read_bytes() == b"log"
    assert logs.stat().st_mode & 0o777 == directory_mode
    assert logs.stat().st_mtime == 1234567890


def test_publishing_merges_into_a_read_only_directory(tmp_path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir(mode=0o500)
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as tar:
        entry = tarfile.TarInfo("logs/run.log")
        entry.size = 3
        tar.addfile(entry, io.BytesIO(b"log"))

    extract_tar_stream([payload.getvalue()], str(tmp_path))

    assert (logs / "run.log").read_bytes() == b"log"
