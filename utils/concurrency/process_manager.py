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
        self._jobs = []

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
        # Everything the collector starts - its pool workers, esentutl,
        # vssadmin - joins this job, so cancel or close can end all of it.
        # Terminating the collector alone left its pool workers running.
        try:
            from utils.concurrency.process_tree import JobObject
            job = JobObject()
            if job.assign(process.pid):
                self._jobs.append(job)
            else:
                job.close()
        except Exception:
            pass

        return TaskHandle(message_queue=message_queue, process=process)

    def kill_tree(self, grace: float = 3.0):
        """End every managed process and everything it started, now."""
        from utils.concurrency.process_tree import kill_tree
        for job in self._jobs:
            job.terminate()
        for p in self._processes:
            try:
                kill_tree(p.pid, grace=grace)
            except Exception:
                pass
            try:
                p.join(timeout=2)
            except Exception:
                pass

    def any_alive(self) -> bool:
        return any(p.is_alive() for p in self._processes)

    def shutdown(self, grace: float = 1.0, kill: bool = True):
        """Clean up all managed resources.

        ``grace``: seconds a process gets to finish on its own (a cancelled
        collection stops between artifacts, deletes its shadow copy and closes
        its custody record - a half-written database is worse than a few
        seconds' wait). After that the whole process TREE is ended, not just
        the collector: its pool workers used to be left running.
        """
        for p in self._processes:
            if p.is_alive():
                p.join(timeout=max(0.0, grace))
        if kill and self.any_alive():
            self.kill_tree(grace=2.0)
        for job in self._jobs:
            job.close()
        self._jobs.clear()
        self._processes.clear()

        # Shutdown the manager last
        if hasattr(self, 'manager'):
            try:
                # On Windows, manager shutdown can sometimes be noisy if
                # children are still cleaning up.
                self.manager.shutdown()
            except Exception:
                pass
            proc = getattr(self.manager, "_process", None)
            try:
                if proc is not None and proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=2)
            except Exception:
                pass
