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

    # A real count of finished work: (completed, total, label). Distinct from
    # simple_progress_updated, which carries a parser's hard-coded step CONSTANT
    # and so runs backwards whenever tasks finish out of order.
    task_progress_updated = pyqtSignal(int, int, str)
    
    # Log message update
    log_updated = pyqtSignal(str)
    
    # Task completion signals
    task_completed = pyqtSignal(str, object)  # task_id, result
    task_error = pyqtSignal(str, str, str)    # task_id, error_msg, traceback

    # One artifact's parse outcome (utils.parse_status.ArtifactOutcome as a
    # dict), produced in the collector process and recorded by the GUI.
    parse_status_reported = pyqtSignal(object)

    # One parser's progress event (utils.parse_logging.ArtifactRun.emit):
    # start / file / now / records / warning / line / done, for the
    # parsing dialog's checklist.
    artifact_progress = pyqtSignal(object)

    # The collector made (or deleted) the run's shadow copy: (action, id).
    # The GUI keeps the IDs so it can delete them itself if it ever has to
    # kill the collector before the collector cleans up.
    shadow_copy_event = pyqtSignal(str, str)
    
    def __init__(self, message_queue: multiprocessing.Queue, process=None):
        super().__init__()
        self.message_queue = message_queue
        # The collector process, when known: if it dies without sending DONE
        # (killed, crashed in C code) the reporter must still end.
        self.process = process
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
                    elif msg_type == "task_progress":
                        self.task_progress_updated.emit(
                            int(msg.get("completed", 0)),
                            int(msg.get("total", 0)),
                            msg.get("message", ""))
                    elif msg_type == "log_message":
                        self.log_updated.emit(msg.get("message", ""))
                    elif msg_type == "task_complete":
                        self.task_completed.emit(msg.get("task_id", ""), msg.get("result"))
                    elif msg_type == "parse_status":
                        self.parse_status_reported.emit(msg.get("outcome") or {})
                    elif msg_type == "log_records":
                        # A worker process's log records, batched: filed
                        # under the case here, where case logging is set up.
                        from utils.parse_logging import forward_log_records
                        forward_log_records(msg)
                    elif msg_type == "log_record":
                        from utils.parse_logging import forward_log_record
                        forward_log_record(msg)
                    elif msg_type == "artifact_progress":
                        self.artifact_progress.emit(msg.get("event") or {})
                    elif msg_type == "task_error":
                        self.task_error.emit(msg.get("task_id", ""), msg.get("error", ""), msg.get("traceback", ""))
                    elif msg_type in ("shadow_copy_created", "shadow_copy_deleted"):
                        self.shadow_copy_event.emit(msg_type.rsplit("_", 1)[1], msg.get("id") or "")
                elif isinstance(msg, str) and msg == "DONE":
                    break
                    
            except queue.Empty:
                if self.process is not None:
                    try:
                        alive = self.process.is_alive()
                    except Exception:
                        alive = False
                    if not alive:
                        self._drain_after_exit()
                        break
                continue
            except (EOFError, BrokenPipeError, ConnectionError, OSError):
                # The manager behind the queue is gone (shut down on cancel):
                # every further get() fails at once. Looping here used to spin
                # a core at 100% for the rest of the session.
                break
            except Exception:
                # A malformed message: skip it, keep reading.
                continue

    def _drain_after_exit(self):
        """Deliver what the dead process managed to queue, then stop."""
        for _ in range(10000):
            try:
                msg = self.message_queue.get_nowait()
            except Exception:
                return
            if isinstance(msg, dict) and msg.get("type") == "log_message":
                self.log_updated.emit(msg.get("message", ""))
            elif isinstance(msg, dict) and msg.get("type") == "parse_status":
                self.parse_status_reported.emit(msg.get("outcome") or {})
            elif isinstance(msg, dict) and msg.get("type") == "log_records":
                from utils.parse_logging import forward_log_records
                forward_log_records(msg)
            elif isinstance(msg, dict) and msg.get("type") == "log_record":
                from utils.parse_logging import forward_log_record
                forward_log_record(msg)
            elif isinstance(msg, dict) and msg.get("type") in ("shadow_copy_created", "shadow_copy_deleted"):
                self.shadow_copy_event.emit(msg["type"].rsplit("_", 1)[1], msg.get("id") or "")

    def stop(self):
        """Gracefully stops the reporter thread."""
        self._is_running = False
