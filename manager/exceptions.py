class CoinjoinEmulatorError(RuntimeError):
    """Base exception for expected emulator runtime failures."""


class RpcError(CoinjoinEmulatorError):
    """Raised when an emulator RPC endpoint returns an error response."""


class StartupError(CoinjoinEmulatorError):
    """Raised when emulator infrastructure cannot be started."""
