"""The structural types the engines share with the clients and the CLI."""

from typing import Protocol


class EmulatorClient(Protocol):
    """The client surface the engines rely on, whichever engine created it."""

    name: str
    delay: tuple[int, int]
    stop: tuple[int, int]

    def get_new_address(self) -> str: ...
    def list_coins(self) -> object: ...
    def list_unspent_coins(self) -> object: ...
    def list_keys(self) -> object: ...
    def stop_coinjoin(self) -> object: ...
    def wait_wallet(self, timeout: int | None = None) -> bool: ...


class InvoiceDistributor(Protocol):
    """The distributor surface the engines use to fund wallet invoices."""

    def get_new_address(self) -> str: ...
    def get_balance(self) -> int: ...
    def wait_wallet(self, timeout: int | None = None) -> bool: ...
    def send(self, invoices: object) -> object: ...


class EngineArgs(Protocol):
    """The command-line options the engines read."""

    command: str
    scenario: str | None
    image_prefix: str
    force_rebuild: bool
    proxy: str
    control_ip: str
    btc_node_ip: str
    wasabi_backend_ip: str
    in_cluster: bool
