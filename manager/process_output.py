"""Helpers for streaming output from subprocesses."""

import subprocess
from queue import Queue
from threading import Thread
from typing import Optional, TextIO, Tuple


def stream_process_output(process: subprocess.Popen[str]) -> None:
    """Stream stdout and stderr concurrently while preserving their labels."""
    assert process.stdout is not None
    assert process.stderr is not None

    output_queue: Queue[Tuple[str, Optional[str]]] = Queue()

    def read_stream(stream: TextIO, stream_name: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                output_queue.put((stream_name, line))
        finally:
            stream.close()
            output_queue.put((stream_name, None))

    readers = [
        Thread(target=read_stream, args=(process.stdout, "STDOUT"), daemon=True),
        Thread(target=read_stream, args=(process.stderr, "STDERR"), daemon=True),
    ]
    for reader in readers:
        reader.start()

    finished_streams = 0
    while finished_streams < len(readers):
        stream_name, line = output_queue.get()
        if line is None:
            finished_streams += 1
        else:
            print(f"  [{stream_name}] {line.rstrip()}")

    for reader in readers:
        reader.join()
