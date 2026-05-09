import multiprocessing
import queue
from PyQt5.QtCore import QThread, pyqtSignal
from .models import ProgressUpdate
from typing import Optional, Dict, Any

class Progress_Reporter(QThread):
    """
    Component that aggregates and reports execution progress from multiple
    worker processes/threads to the main GUI thread using PyQt5 signals.
    """
    # PyQt5_Signal: standard signature for detailed updates
    progress_updated = pyqtSignal(ProgressUpdate)
    
    # Generic update for simple percentage and status string
    simple_progress_updated = pyqtSignal(int, str)
    
    # Log message update
    log_updated = pyqtSignal(str)
    
    # Task completion signals
    task_completed = pyqtSignal(str, object)  # task_id, result
    task_error = pyqtSignal(str, str, str)    # task_id, error_msg, traceback
    
    def __init__(self, message_queue: multiprocessing.Queue):
        super().__init__()
        self.message_queue = message_queue
        self._is_running = True

    def run(self):
        """Continuously polls the multiprocessing queue for progress updates."""
        while self._is_running:
            try:
                # Use a small timeout to allow for non-blocking shutdown
                msg = self.message_queue.get(timeout=0.1)
                
                if isinstance(msg, dict):
                    msg_type = msg.get("type")
                    if msg_type == "DONE":
                        break
                    elif msg_type == "progress_update" and "data" in msg:
                        data = msg["data"]
                        if isinstance(data, ProgressUpdate):
                            self.progress_updated.emit(data)
                        else:
                            # fallback dictionary unpack
                            update = ProgressUpdate(**data)
                            self.progress_updated.emit(update)
                    elif msg_type == "simple_progress":
                        self.simple_progress_updated.emit(msg.get("step_index", 0), msg.get("message", ""))
                    elif msg_type == "log_message":
                        self.log_updated.emit(msg.get("message", ""))
                    elif msg_type == "task_complete":
                        self.task_completed.emit(msg.get("task_id", ""), msg.get("result"))
                    elif msg_type == "task_error":
                        self.task_error.emit(msg.get("task_id", ""), msg.get("error", ""), msg.get("traceback", ""))
                elif isinstance(msg, str) and msg == "DONE":
                    break
                    
            except queue.Empty:
                continue
            except Exception as e:
                # Silently catch malformed messages or connection drops to keep thread alive
                pass

    def stop(self):
        """Gracefully stops the reporter thread."""
        self._is_running = False
