import multiprocessing
from typing import Optional, Any

class Cancellation_Token:
    """
    Signal mechanism that allows graceful cancellation of running tasks
    across thread and process pools.
    """
    def __init__(self, manager: Optional[Any] = None):
        if manager:
            self._event = manager.Event()
        else:
            self._event = multiprocessing.Event()
            
    def cancel(self):
        """Signal that the operation should be cancelled."""
        self._event.set()
        
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._event.is_set()
