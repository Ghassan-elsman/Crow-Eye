"""
Truncation Auditor Service for EYE.
Maintains forensic audit trail for chain of custody compliance.
"""

import json
import hashlib
import re
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List


class TruncationAuditor:
    """
    Manages forensic audit trail for truncation events.
    
    Writes append-only log to case directory for chain of custody compliance.
    Supports buffering for performance and export functionality.
    
    Log format:
    [timestamp] [action] [message_id] tokens=[count] reason=[reason] hash=[hash] metadata=[json]
    
    Actions:
    - SUMMARIZED: Message was included in a summary
    - TRUNCATED: Message was removed from history
    - PRESERVED: Message was marked for preservation (auto-detected evidence)
    - PINNED: Message was manually pinned by investigator
    - UNPINNED: Message was unpinned by investigator
    - BUDGET_REDUCED: A context component budget was dynamically adjusted
    """
    
    def __init__(self, case_directory: str):
        """
        Initialize auditor with case directory path.
        
        Args:
            case_directory: Path to active case directory
        """
        self.case_directory = Path(case_directory)
        self.logs_dir = self.case_directory / "EYE_Logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.logs_dir / "truncation_audit.log"
        self.logger = logging.getLogger(__name__)
        
        # Create log file if it doesn't exist
        if not self.log_path.exists():
            self.log_path.touch()
        
        # Buffer for pending log entries (for performance)
        self.buffer: List[str] = []
        self.buffer_max_size = 10
        
        # In-memory buffer for failed writes (max 1000 entries)
        self.failed_writes_buffer: List[str] = []
        self.failed_writes_max_size = 1000
        
        # Retry configuration
        self.max_retries = 3
        self.retry_base_delay = 0.1  # 100ms base delay for exponential backoff
    
    def log_event(
        self,
        action: str,
        message_id: str,
        token_count: int,
        reason: str,
        message_hash: str,
        metadata: Optional[Dict] = None
    ):
        """
        Log a truncation or preservation event.
        
        Args:
            action: Type of action (SUMMARIZED, TRUNCATED, PRESERVED, PINNED, UNPINNED)
            message_id: Unique message identifier
            token_count: Token count of message
            reason: Reason for action (e.g., "budget_exceeded", "evidence_detected")
            message_hash: SHA-256 hash of message content for verification
            metadata: Additional context (e.g., patterns_found, original_tokens)
        """
        # Format log entry
        timestamp = datetime.now().isoformat()
        metadata_json = json.dumps(metadata or {})
        
        log_entry = (
            f"[{timestamp}] {action} {message_id} "
            f"tokens={token_count} reason={reason} "
            f"hash={message_hash} metadata={metadata_json}\n"
        )
        
        # Add to buffer
        self.buffer.append(log_entry)
        
        # Flush if buffer is full
        if len(self.buffer) >= self.buffer_max_size:
            self._flush_buffer()
    
    def _flush_buffer(self):
        """
        Write buffered log entries to disk with retry logic and exponential backoff.
        
        Error Handling :
            - Retries write operation up to 3 times with exponential backoff
            - If all retries fail, buffers audit entries in memory (max 1000 entries)
            - Emits critical warning about chain of custody risk
            - Attempts to flush buffer on next successful write
        """
        if not self.buffer:
            return
        
        # Try to flush any previously failed writes first
        if self.failed_writes_buffer:
            self._attempt_flush_failed_writes()
        
        # Attempt to write current buffer with retry logic
        for attempt in range(self.max_retries):
            try:
                with open(self.log_path, 'a', encoding='utf-8') as f:
                    f.writelines(self.buffer)
                self.buffer.clear()
                self.logger.debug(f"Successfully flushed audit buffer (attempt {attempt + 1})")
                return
            except Exception as e:
                delay = self.retry_base_delay * (2 ** attempt)  # Exponential backoff
                self.logger.warning(
                    f"Audit trail write failed (attempt {attempt + 1}/{self.max_retries}): {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                if attempt < self.max_retries - 1:
                    time.sleep(delay)
        
        # All retries failed - buffer in memory
        self.logger.error(
            f"CRITICAL: Audit trail write failed after {self.max_retries} attempts. "
            f"Buffering {len(self.buffer)} entries in memory. Chain of custody at risk!"
        )
        
        # Move entries to failed writes buffer
        self.failed_writes_buffer.extend(self.buffer)
        self.buffer.clear()
        
        # Enforce maximum buffer size
        if len(self.failed_writes_buffer) > self.failed_writes_max_size:
            overflow = len(self.failed_writes_buffer) - self.failed_writes_max_size
            self.logger.error(
                f"CRITICAL: Failed writes buffer overflow! Dropping {overflow} oldest entries."
            )
            self.failed_writes_buffer = self.failed_writes_buffer[-self.failed_writes_max_size:]
    
    def _attempt_flush_failed_writes(self):
        """
        Attempt to flush previously failed writes to disk.
        
        This is called before each new flush attempt to recover from
        temporary I/O failures.
        """
        if not self.failed_writes_buffer:
            return
        
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.writelines(self.failed_writes_buffer)
            
            recovered_count = len(self.failed_writes_buffer)
            self.failed_writes_buffer.clear()
            self.logger.info(
                f"Successfully recovered {recovered_count} failed audit entries"
            )
        except Exception as e:
            self.logger.warning(f"Failed to flush previously failed writes: {e}")
    
    def export_audit_trail(self, output_path: str) -> bool:
        """
        Export the current audit trail to a standalone file.
        
        Args:
            output_path: Destination path for the audit trail export
            
        Returns:
            bool: True if export succeeded, False otherwise
        """
        try:
            self._flush_buffer()
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            
            import shutil
            shutil.copy2(self.log_path, output_path)
            self.logger.info(f"Audit trail exported to {output_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to export audit trail: {e}")
            return False

    def export_audit_trail_json(self, output_path: str) -> bool:
        """
        Export the audit trail in a structured JSON format for machine readability.
        
        This converts the flat log file into a JSON array of events, making it
        easier to analyze in external forensic tools or the EYE UI.
        
        Args:
            output_path: Destination path for the JSON export
            
        Returns:
            bool: True if export succeeded, False otherwise
        """
        try:
            self._flush_buffer()
            events = []
            
            if self.log_path.exists():
                with open(self.log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        # Parse the log format:
                        # [timestamp] ACTION ID tokens=X reason=Y hash=Z metadata={...}
                        match = re.match(
                            r'\[(?P<timestamp>[^\]]+)\] (?P<action>\w+) (?P<id>\S+) '
                            r'tokens=(?P<tokens>\d+) reason=(?P<reason>\S+) '
                            r'hash=(?P<hash>\S+) metadata=(?P<metadata>.*)',
                            line.strip()
                        )
                        if match:
                            event = match.groupdict()
                            try:
                                event['metadata'] = json.loads(event['metadata'])
                            except json.JSONDecodeError:
                                pass
                            events.append(event)
            
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(events, f, indent=2, ensure_ascii=False)
                
            self.logger.info(f"Structured audit trail exported to {output_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to export JSON audit trail: {e}")
            return False
            
    def auto_export_json(self) -> bool:
        """
        """
        output_path = self.logs_dir / "audit_trail.json"
        return self.export_audit_trail_json(str(output_path))
    
    def get_audit_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics of audit trail.
        
        Returns:
            Dictionary containing:
                - total_events: Total number of logged events
                - summarized_count: Number of SUMMARIZED events
                - preserved_count: Number of PRESERVED events
                - pinned_count: Number of PINNED events
                - first_event: ISO timestamp of first event
                - last_event: ISO timestamp of last event
                - failed_writes_count: Number of entries in failed writes buffer
                - chain_of_custody_at_risk: Boolean indicating if audit trail is compromised
        """
        # Flush buffer to ensure all events are counted
        self._flush_buffer()
        
        summary = {
            "total_events": 0,
            "summarized_count": 0,
            "preserved_count": 0,
            "pinned_count": 0,
            "first_event": None,
            "last_event": None,
            "failed_writes_count": len(self.failed_writes_buffer),
            "chain_of_custody_at_risk": len(self.failed_writes_buffer) > 0
        }
        
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
                if not lines:
                    return summary
                
                summary["total_events"] = len(lines)
                
                # Parse first and last timestamps
                first_line = lines[0]
                last_line = lines[-1]
                
                # Extract timestamp from format: [timestamp] ...
                if first_line.startswith('['):
                    summary["first_event"] = first_line[1:first_line.index(']')]
                if last_line.startswith('['):
                    summary["last_event"] = last_line[1:last_line.index(']')]
                
                # Count action types
                for line in lines:
                    if ' SUMMARIZED ' in line:
                        summary["summarized_count"] += 1
                    elif ' PRESERVED ' in line:
                        summary["preserved_count"] += 1
                    elif ' PINNED ' in line:
                        summary["pinned_count"] += 1
        
        except Exception as e:
            self.logger.error(f"Error reading audit log: {e}")
        
        return summary
    
    def __del__(self):
        """Flush buffer on destruction."""
        self._flush_buffer()
