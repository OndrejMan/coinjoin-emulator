"""Protocol definition for Wasabi backend implementations."""

from typing import Protocol, Any


class WasabiBackendProtocol(Protocol):
    """Protocol that all Wasabi backend implementations must follow."""
    
    host: str
    port: int
    internal_ip: str
    proxy: str
    
    def _rpc(self, request: dict[str, Any]) -> Any:
        """Execute an RPC call to the backend.
        
        Args:
            request: The RPC request dictionary
            
        Returns:
            The result of the RPC call, or "timeout" on timeout
        """
        ...
    
    def _get_status(self) -> dict[str, Any]:
        """Get the backend status.
        
        Returns:
            Status information as a dictionary
        """
        ...
    
    def wait_ready(self) -> None:
        """Wait until the backend is ready to accept requests."""
        ...
