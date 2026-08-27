from .wasabi_client_base import WasabiClientBase


class WasabiClientV204(WasabiClientBase):

    def __init__(
        self,
        host: str = "localhost",
        port: int = 37128,
        name: str = "wasabi-client",
        proxy: str = "",
        version: str = "2.0.4",
        delay: tuple[int, int] = (0, 0),
        stop: tuple[int, int] = (0, 0),
    ) -> None:
        super().__init__(host, port, name, proxy, version, delay, stop)
