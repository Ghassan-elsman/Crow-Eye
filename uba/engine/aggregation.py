"""
USN-journal file activity: classification, rename pairing, Recycle-Bin
soft-delete detection and burst aggregation.

The journal in a real case holds ~200k rows; emitting one activity per row
would be unreadable and unusable. Rows are classified into operation
categories, rename halves are paired by (volume, frn) with adjacent USNs,
moves into $Recycle.Bin become soft-delete events, and the remainder is
grouped into "bursts": same (volume, folder bucket, operation) within a
300-second gap, capped at 5000 rows per burst.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from uba.engine import description
from uba.utils.timeparse import epoch_seconds

logger = logging.getLogger(__name__)

GAP_SECONDS = 300
MAX_BURST_ROWS = 5000
SAMPLE_FILENAMES = 10

OP_CREATE = "created"
OP_DELETE = "deleted"
OP_MODIFY = "edited"
OP_RENAME = "renamed"
OP_SOFT_DELETE = "soft_deleted"


def classify_reason(reason: Optional[str]) -> Optional[str]:
    """Map a pipe-joined USN reason string onto one operation category.

    Precedence: delete > create > rename > modify. A row that is only
    CLOSE / SECURITY_CHANGE / metadata noise returns None (skipped, the
    skip count is reported to coverage stats).
    """
    if not reason:
        return None
    r = reason.upper()
    if "FILE_DELETE" in r:
        return OP_DELETE
    if "FILE_CREATE" in r:
        return OP_CREATE
    if "RENAME_OLD_NAME" in r or "RENAME_NEW_NAME" in r:
        return OP_RENAME
    if "DATA_OVERWRITE" in r or "DATA_EXTEND" in r or "DATA_TRUNCATION" in r:
        return OP_MODIFY
    return None


@dataclass
class UsnRow:
    rowid: int
    volume: str
    filename: str
    usn: int
    frn: Optional[int]
    parent_frn: Optional[int]
    ts: str                      # normalized 'YYYY-MM-DD HH:MM:SS'
    reason: str
    epoch: float = 0.0
    path: Optional[str] = None   # reconstructed path when resolvable


@dataclass
class RenamePair:
    old: Optional[UsnRow]
    new: Optional[UsnRow]

    @property
    def anchor(self) -> UsnRow:
        return self.new or self.old

    def is_recycle_move(self) -> bool:
        """A rename whose NEW name is a $R/$I Recycle-Bin entry is the
        Explorer 'move to Recycle Bin' operation (soft delete)."""
        if not self.new:
            return False
        name = (self.new.filename or "").upper()
        in_bin = "$RECYCLE" in (self.new.path or "").upper() if self.new.path else False
        return in_bin or ((name.startswith("$R") or name.startswith("$I"))
                          and len(name) > 2)


@dataclass
class Burst:
    volume: str
    folder_bucket: str
    op: str
    rows: List[UsnRow] = field(default_factory=list)

    @property
    def ts_start(self) -> str:
        return self.rows[0].ts

    @property
    def ts_end(self) -> str:
        return self.rows[-1].ts

    def rowid_range(self) -> Tuple[int, int]:
        ids = [r.rowid for r in self.rows]
        return min(ids), max(ids)

    def sample_names(self) -> List[str]:
        seen, names = set(), []
        for row in self.rows:
            if row.filename and row.filename not in seen:
                seen.add(row.filename)
                names.append(row.filename)
            if len(names) >= SAMPLE_FILENAMES:
                break
        return names

    def extension_histogram(self) -> Dict[str, int]:
        hist: Dict[str, int] = {}
        for row in self.rows:
            name = row.filename or ""
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext and len(ext) <= 5:
                hist[ext] = hist.get(ext, 0) + 1
        return dict(sorted(hist.items(), key=lambda kv: -kv[1])[:8])


def pair_renames(rows: List[UsnRow]) -> List[RenamePair]:
    """Pair RENAME_OLD_NAME / RENAME_NEW_NAME halves.

    Halves belong together when they share (volume, frn) and are adjacent
    in USN order. Unpaired halves become single-sided pairs — shown with
    honest "(previous/new name not recorded)" wording, never dropped.
    """
    pairs: List[RenamePair] = []
    pending_old: Dict[Tuple[str, Optional[int]], UsnRow] = {}
    for row in sorted(rows, key=lambda r: (r.volume, r.usn)):
        reason = row.reason.upper()
        key = (row.volume, row.frn)
        if "RENAME_OLD_NAME" in reason:
            orphan = pending_old.pop(key, None)
            if orphan is not None:
                pairs.append(RenamePair(old=orphan, new=None))
            pending_old[key] = row
        elif "RENAME_NEW_NAME" in reason:
            old = pending_old.pop(key, None)
            pairs.append(RenamePair(old=old, new=row))
    pairs.extend(RenamePair(old=row, new=None) for row in pending_old.values())
    return pairs


@dataclass
class RenameChain:
    """The ordered name history of a single file (one MFT record / frn)."""
    volume: str
    frn: Optional[int]
    names: List[str]                 # [oldest, …, current]
    rows: List[UsnRow] = field(default_factory=list)

    @property
    def ts_start(self) -> str:
        return self.rows[0].ts

    @property
    def ts_end(self) -> str:
        return self.rows[-1].ts

    @property
    def path(self) -> Optional[str]:
        for row in self.rows:
            if row.path:
                return row.path
        return None


def _is_recycle_name(name: str, path: Optional[str]) -> bool:
    n = (name or "").upper()
    if path and "$RECYCLE" in path.upper():
        return True
    return (n.startswith("$R") or n.startswith("$I")) and len(n) > 2


def build_rename_chains(rename_rows: List["UsnRow"]):
    """Group rename rows by (volume, frn) and reconstruct each file's ordered
    name history.

    Returns (chains, recycle_rows): `chains` is a list of RenameChain (name
    history, consecutive-deduped, split on discontinuity from MFT-record
    reuse); `recycle_rows` are rename rows whose target is a Recycle-Bin
    entry ($R/$I) — handed back to the soft-delete path, not treated as a
    rename.
    """
    by_frn: Dict[Tuple[str, Optional[int]], List["UsnRow"]] = {}
    recycle_rows: List["UsnRow"] = []
    for row in rename_rows:
        if "RENAME_NEW_NAME" in row.reason.upper() and _is_recycle_name(
                row.filename, row.path):
            recycle_rows.append(row)
            continue
        by_frn.setdefault((row.volume, row.frn), []).append(row)

    chains: List[RenameChain] = []
    for (volume, frn), rows in by_frn.items():
        rows = sorted(rows, key=lambda r: r.usn)
        cur_names: List[str] = []
        cur_rows: List["UsnRow"] = []

        def flush():
            if len(cur_names) >= 2:
                chains.append(RenameChain(volume=volume, frn=frn,
                                          names=list(cur_names), rows=list(cur_rows)))

        for row in rows:
            name = row.filename or ""
            if not name:
                continue
            reason = row.reason.upper()
            if cur_names and "RENAME_OLD_NAME" in reason and name != cur_names[-1]:
                # An OLD name that doesn't continue the current chain => the
                # record was reused for a different file; start a new chain.
                flush()
                cur_names, cur_rows = [], []
            if not cur_names or name != cur_names[-1]:   # consecutive-dedup
                cur_names.append(name)
            cur_rows.append(row)
        flush()
    return chains, recycle_rows


class BurstAggregator:
    """Groups classified USN rows into readable bursts."""

    def __init__(self, gap_seconds: int = GAP_SECONDS,
                 max_rows: int = MAX_BURST_ROWS):
        self.gap_seconds = gap_seconds
        self.max_rows = max_rows

    def aggregate(self, rows: Iterator[UsnRow], op: str) -> List[Burst]:
        open_bursts: Dict[Tuple[str, str], Burst] = {}
        finished: List[Burst] = []
        for row in rows:
            bucket = description.folder_label(row.path or row.filename)
            key = (row.volume, bucket)
            burst = open_bursts.get(key)
            if burst is not None:
                gap = row.epoch - burst.rows[-1].epoch
                if gap > self.gap_seconds or len(burst.rows) >= self.max_rows:
                    finished.append(burst)
                    burst = None
            if burst is None:
                burst = Burst(volume=row.volume, folder_bucket=bucket, op=op)
                open_bursts[key] = burst
            burst.rows.append(row)
        finished.extend(open_bursts.values())
        finished.sort(key=lambda b: b.rows[0].epoch)
        return finished


def usn_row_from_db(rowid, volume, filename, usn, frn, parent_frn,
                    ts_norm, reason, path=None) -> Optional[UsnRow]:
    epoch = epoch_seconds(ts_norm)
    if epoch is None:
        return None
    return UsnRow(rowid=rowid, volume=volume or "", filename=filename or "",
                  usn=usn or 0, frn=frn, parent_frn=parent_frn, ts=ts_norm,
                  reason=reason or "", epoch=epoch, path=path)
