# pylint: disable=unused-argument
from collections.abc import Mapping
from typing import overload

class Response:
    status_code: int
    text: str
    content: bytes
    def json(self) -> Mapping[str, object]: ...
    def raise_for_status(self) -> None: ...

class RequestException(Exception): ...
class Timeout(RequestException): ...

class _Exceptions:
    RequestException: type[RequestException]
    Timeout: type[Timeout]

exceptions: _Exceptions

def get(
    url: str,
    *args: object,
    timeout: float | tuple[float, float] | None = ...,
    **kwargs: object,
) -> Response: ...

def post(
    url: str,
    *args: object,
    json: object = ...,
    timeout: float | tuple[float, float] | None = ...,
    **kwargs: object,
) -> Response: ...

@overload
def request(
    method: str,
    url: str,
    *args: object,
    timeout: float | tuple[float, float] | None = ...,
    **kwargs: object,
) -> Response: ...
@overload
def request(
    method: str,
    url: str,
    *args: object,
    **kwargs: object,
) -> Response: ...
