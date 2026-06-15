"""Protocol definition for Wasabi coordinator implementations."""

from typing import Protocol


class WasabiCoordinatorProtocol(Protocol):
    """Protocol that all Wasabi coordinator implementations must follow."""
    
    host: str
    port: int
    internal_ip: str
    proxy: str
    
    def get_status(self) -> dict[str, object] | None:
        """Get coordinator status.
        
        Returns:
            Status information as a dictionary, or None on error
        """
        raise NotImplementedError
    
    def _get_rounds(self) -> dict[str, object] | None:
        """Get active coinjoin rounds.
        
        Returns:
            Round information as a dictionary, or None on error
        """
        raise NotImplementedError
    
    def wait_ready(self) -> None:
        """Wait for coordinator to be ready."""
        raise NotImplementedError
