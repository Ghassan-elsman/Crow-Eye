from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable

@dataclass
class ProgressUpdate:
    """Dataclass containing detailed progress statistics."""
    current_file: str = ""
    processed_count: int = 0
    total_count: int = 0
    artifacts_found: int = 0
    artifacts_collected: int = 0
    artifacts_failed: int = 0
    elapsed_time: float = 0.0
    status_message: str = ""
    data_type: str = ""
    percent_complete: float = 0.0

@dataclass
class Parser_Task:
    """Encapsulates a CPU-intensive forensic artifact parsing operation."""
    task_id: str
    target_function: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    data_type: str = "generic"

@dataclass
class Correlation_Task:
    """Encapsulates a CPU-intensive correlation operation."""
    task_id: str
    target_function: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
