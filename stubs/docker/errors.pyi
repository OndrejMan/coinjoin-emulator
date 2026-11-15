# pylint: disable=unused-argument
class ImageNotFound(Exception): ...
class NotFound(Exception): ...

class APIError(Exception):
    explanation: str | None
    def __init__(
        self,
        message: str = ...,
        response: object | None = ...,
        explanation: str | None = ...,
    ) -> None: ...
