import multiprocessing
import os
import sys
from typing import Callable, Any, Optional
from dataclasses import dataclass

@dataclass
class TaskHandle:
    message_queue: Any
    process: multiprocessing.Process

class Process_Manager:
    """
    Component responsible for creating, managing, and coordinating
    multiple processes for CPU-bound operations like artifact parsing.
    """
    def __init__(self):
        # We use 'spawn' globally as it's the safest method for GUI apps (PyQt5)
        # to avoid deadlocks or state inheritance issues common with 'fork'.
        try:
            self.context = multiprocessing.get_context('spawn')
        except ValueError:
            # Fallback if spawn is not available (though it should be in Python 3)
            self.context = multiprocessing.get_context()
                
        self.manager = self.context.Manager()
        self._processes = []

    def run_parser_task(
        self,
        target_function: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None
    ) -> TaskHandle:
        """
        Executes a CPU-bound target function in a separate process.
        Returns a multiprocessing Queue that the worker uses to send back logs and steps.
        """
        if kwargs is None:
            kwargs = {}
            
        message_queue = self.manager.Queue()
        # Add queue to kwargs so the standalone target function can use it
        kwargs['message_queue'] = message_queue
        
        process = self.context.Process(
            target=target_function,
            args=args,
            kwargs=kwargs,
            daemon=False
        )
        process.start()
        self._processes.append(process)
        
        return TaskHandle(message_queue=message_queue, process=process)

    def shutdown(self):
        """Clean up all managed resources gracefully."""
        for p in self._processes:
            if p.is_alive():
                # Try to join first (maybe it's finishing)
                p.join(timeout=1)
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=2)
        self._processes.clear()
        
        # Shutdown the manager last
        if hasattr(self, 'manager'):
            try:
                # On Windows, manager shutdown can sometimes be noisy if 
                # children are still cleaning up.
                self.manager.shutdown()
            except Exception:
                pass
