class ApiException(Exception):
    status: int | None
    body: str | None
