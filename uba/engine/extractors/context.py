"""Shared state handed to every extractor."""

import logging
import ntpath
from typing import Dict, List, Optional, Tuple

from uba.utils import log_parser
from uba.utils.timeparse import epoch_seconds, normalize_ts

logger = logging.getLogger(__name__)


class ExtractorContext:
    """Read-only services: DB pool, actor resolver, session index and a
    lazily-built Security 4688 index used for artifact↔log time-delta
    correlation."""

    def __init__(self, db_pool, resolver, sessions, stats: Optional[dict] = None):
        self.pool = db_pool
        self.resolver = resolver
        self.sessions = sessions
        self.stats = stats if stats is not None else {}
        self._index_4688: Optional[List[Tuple[float, str, int]]] = None

    # ------------------------------------------------------------------ #
    def session_context(self, ts: Optional[str]) -> str:
        return self.sessions.context_for(epoch_seconds(ts)) if ts else ""

    def bump(self, key: str, n: int = 1):
        self.stats[key] = self.stats.get(key, 0) + n

    # ------------------------------------------------------------------ #
    def _build_4688_index(self) -> List[Tuple[float, str, int]]:
        index: List[Tuple[float, str, int]] = []
        conn = self.pool.get("logs")
        if conn is None or not self.pool.has_table("logs", "SecurityLogs"):
            return index
        try:
            for rowid, ts, keywords in conn.execute(
                    "SELECT rowid, EventTimestampUTC, Keywords "
                    "FROM SecurityLogs WHERE EventID = 4688"):
                info = log_parser.parse_payload(4688, keywords)
                proc = info.get("new_process_name", "")
                epoch = epoch_seconds(normalize_ts(ts))
                if proc and epoch is not None:
                    basename = ntpath.basename(proc.replace("/", "\\")).lower()
                    index.append((epoch, basename, rowid))
        except Exception as e:
            logger.warning("UBA: 4688 index build failed: %s", e)
        index.sort()
        return index

    def find_4688(self, exe_name: Optional[str], ts: Optional[str],
                  delta_seconds: int = 5) -> List[int]:
        """rowids of 4688 process-creation events for exe_name within
        ±delta_seconds of ts. Empty list = no corroboration."""
        if not exe_name or not ts:
            return []
        if self._index_4688 is None:
            self._index_4688 = self._build_4688_index()
        center = epoch_seconds(ts)
        if center is None or not self._index_4688:
            return []
        needle = ntpath.basename(str(exe_name).replace("/", "\\")).lower()
        if not needle.endswith(".exe"):
            needle_alt = needle + ".exe"
        else:
            needle_alt = needle
        hits = []
        for epoch, basename, rowid in self._index_4688:
            if epoch < center - delta_seconds:
                continue
            if epoch > center + delta_seconds:
                break
            if basename in (needle, needle_alt):
                hits.append(rowid)
        return hits
