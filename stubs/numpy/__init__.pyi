# Stub package for local mypy checks.

from . import random as random

class _IntArrayLike:
    def tolist(self) -> list[int]: ...

def sort(a: object) -> _IntArrayLike: ...
