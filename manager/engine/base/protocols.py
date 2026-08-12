"""The structural types the engines share with the clients and the CLI."""

from typing import Protocol


class EmulatorClient(Protocol):
    """The client surface the engines rely on, whichever engine created it."""

    name: str
    delay: tuple[int, int]
    stop: tuple[int, int]

    def get_new_address(self) -> str: ...
    def get_balance(self) -> int: ...
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
    no_logs: bool
    run_timezone: str
    run_id: str | None
    btcFolder: str
    btc_node_arg: list[str]
    download_btc_data: str
    download_path: str
    controller_done_marker: str
    controller_failed_marker: str
    joinmarket_descriptor_regtest_fallback: bool
    disable_port_forward: bool
    btc_node_image: str
    joinmarket_client_server_image: str
    irc_server_image: str
    coinjoin_infrastructure_local_build: bool
