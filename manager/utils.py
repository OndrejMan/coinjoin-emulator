from collections.abc import Iterator, Sequence
from typing import TypeVar

T = TypeVar("T")


def batched(data: Sequence[T], batch_size: int = 1) -> Iterator[Sequence[T]]:
    length = len(data)
    for ndx in range(0, length, batch_size):
        yield data[ndx : min(ndx + batch_size, length)]
