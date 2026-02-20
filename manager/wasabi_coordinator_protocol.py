"""Protocol definition for Wasabi coordinator implementations."""

from typing import Protocol, Any


class WasabiCoordinatorProtocol(Protocol):
    """Protocol that all Wasabi coordinator implementations must follow."""
    
    host: str
    port: int
    internal_ip: str
    proxy: str
    
    def _get_status(self) -> dict[str, Any] | None:
        """Get coordinator status.
        
        Returns:
            Status information as a dictionary, or None on error
        """
        ...
    
    def _get_rounds(self) -> dict[str, Any] | None:
        """Get active coinjoin rounds.
        
        Returns:
            Round information as a dictionary, or None on error
        """
        ...
    
    def wait_ready(self) -> None:
        """Wait for coordinator to be ready."""
        ...
