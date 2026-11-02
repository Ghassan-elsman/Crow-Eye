"""
What changed between a volume's shadow copies, and now - for the whole volume or chosen folders.

Walking millions of files through every copy is minutes per copy and gigabytes of memory, so the
comparison reads each state's own $MFT instead: every copy (exposed, hidden or in an image) and the
volume as it is now, oldest first, in lockstep, record by record. A record is the same file in two
states when its sequence number is the same; between two consecutive states a file is

    added    in use in the later state and not in the earlier one (or reused: a new sequence)
    deleted  in use in the earlier state and not in the later one (or reused)
    changed  in use in both with the same sequence, and its size or modified time differs.

Folders are summed the same pass: each file's size goes to its folder, then up the tree, giving
every folder's size in every state and its added / deleted / changed counts per interval, counted
over everything below it. Paths come from the folders' own records, newest state first, so a
folder deleted since a copy still has its name.

Results go to the case's Target_Artifacts/shadow_copies.db, read by the Shadow Copies window and,
as any case table, by Eye. Times are UTC. Only NTFS volumes.
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import struct
import time
import uuid
from typing import Callable, Dict, List, Optional, Tuple

DB_NAME = "shadow_copies.db"
FILE_ROWS_CAP = 200000            # changed-file rows kept per run; counts are never capped
_EPOCH_DIFF = 116444736000000000  # FILETIME of 1970-01-01


def _ft_iso(ft: int) -> Optional[str]:
    if not ft:
        return None
    try:
        return datetime.datetime.utcfromtimestamp((ft - _EPOCH_DIFF) / 1e7).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, ValueError, OSError):
        return None


def parse_record(buf: bytes, off: int, size: int):
    """Minimal FILE record: (seq, in_use, is_dir, parent, name, data_size, modified_ft) of a base
    record, or None for an empty or torn record. The long (Win32 / POSIX) name wins over the 8.3
    alias. A fragmented or large file keeps its $DATA in an extension record (through
    $ATTRIBUTE_LIST): such an extension record returns ("ext", base_record, data_size), and the
    base record's own tuple ends with has_data False, so the caller joins the two - without it a
    folder of databases reads as a fraction of its size."""
    if buf[off:off + 4] != b"FILE":
        return None
    rec = bytearray(buf[off:off + size])
    uso, usc = struct.unpack_from("<HH", rec, 4)
    usn = rec[uso:uso + 2]
    for i in range(1, usc):
        end = i * 512
        if end > size or rec[end - 2:end] != usn:
            return None
        rec[end - 2:end] = rec[uso + 2 * i: uso + 2 * i + 2]
    seq, = struct.unpack_from("<H", rec, 0x10)
    flags, = struct.unpack_from("<H", rec, 0x16)
    base, = struct.unpack_from("<Q", rec, 0x20)
    pos, = struct.unpack_from("<H", rec, 0x14)
    if base & 0xFFFFFFFFFFFF:
        if not flags & 1:
            return None
        while pos + 16 <= size:
            atype, alen = struct.unpack_from("<II", rec, pos)
            if atype == 0xFFFFFFFF or alen == 0 or pos + alen > size:
                return None
            if atype == 0x80 and rec[pos + 9] == 0 and rec[pos + 8]:
                vcn, = struct.unpack_from("<q", rec, pos + 0x10)
                if vcn == 0:
                    return ("ext", base & 0xFFFFFFFFFFFF, struct.unpack_from("<q", rec, pos + 0x30)[0])
            pos += alen
        return None
    parent, name, ns_best, dsize, mtime = 0, None, 99, None, 0
    fn_size = 0
    while pos + 16 <= size:
        atype, alen = struct.unpack_from("<II", rec, pos)
        if atype == 0xFFFFFFFF or alen == 0 or pos + alen > size:
            break
        nonres = rec[pos + 8]
        nlen = rec[pos + 9]
        if atype == 0x10 and not nonres:
            coff, = struct.unpack_from("<H", rec, pos + 0x14)
            mtime, = struct.unpack_from("<Q", rec, pos + coff + 8)
        elif atype == 0x30 and not nonres:
            coff, = struct.unpack_from("<H", rec, pos + 0x14)
            c = pos + coff
            ns = rec[c + 0x41]
            rank = {1: 0, 3: 1, 0: 2, 2: 3}.get(ns, 4)
            if rank < ns_best:
                ns_best = rank
                parent = struct.unpack_from("<Q", rec, c)[0] & 0xFFFFFFFFFFFF
                fn_size, = struct.unpack_from("<Q", rec, c + 0x30)
                ln = rec[c + 0x40]
                name = bytes(rec[c + 0x42: c + 0x42 + ln * 2]).decode("utf-16-le", "replace")
        elif atype == 0x80 and nlen == 0 and dsize is None:
            if nonres:
                vcn, = struct.unpack_from("<q", rec, pos + 0x10)
                if vcn == 0:
                    dsize, = struct.unpack_from("<q", rec, pos + 0x30)
            else:
                dsize, = struct.unpack_from("<I", rec, pos + 0x10)
        pos += alen
    if name is None:
        return None
    return (seq, bool(flags & 1), bool(flags & 2), parent, name,
            dsize if dsize is not None else fn_size, mtime, dsize is not None)


class _State:
    """One point in time: a $MFT stream, read a chunk at a time."""

    def __init__(self, label: str, stream, closer=None):
        from Artifacts_Collectors.volume_layout import StreamMft
        self.label = label
        self.mft = StreamMft(stream)
        self.rec = self.mft.rec
        self.size = self.mft.size
        self._closer = closer

    def chunk(self, first: int, count: int) -> bytes:
        return self.mft.read_records(first, count)

    def close(self):
        if self._closer:
            try:
                self._closer()
            except Exception:
                pass


def open_state(spec: dict) -> _State:
    """spec: {'kind': 'live', 'volume': 'C'} | {'kind': 'device', 'device': ...}
    | {'kind': 'hidden', 'volume': 'C', 'shadow_id': ...} | {'kind': 'image', 'image': p, 'partition': n,
    'index': i}; 'label' names the state."""
    from Artifacts_Collectors import shadow_copies as sc
    kind = spec["kind"]
    if kind == "live":
        raw = sc.raw_volume(spec["volume"])
        return _State(spec.get("label") or "now", raw, raw.close)
    if kind in ("device", "hidden"):
        raw = sc.raw_volume(spec["volume"])
        store = sc.find_store(raw, shadow_id=spec["shadow_id"])
        return _State(spec["label"], sc.snapshot_stream(store), raw.close)
    if kind == "image":
        _strategy, vol = sc.open_image_volume(spec["image"], spec["partition"])
        if spec.get("index") is None:
            return _State(spec["label"], vol)
        return _State(spec["label"], sc.snapshot_stream(sc.find_store(vol, index=spec["index"])))
    raise ValueError("unknown state kind %r" % kind)


def compare(specs: List[dict], scope: str = "", case_dir: Optional[str] = None, volume: str = "C",
            progress: Callable = None, is_cancelled: Callable = None, chunk_records: int = 4096) -> dict:
    """Compare consecutive states (oldest first; the last is normally now). Returns the run's
    summary and writes it to the case's shadow_copies.db (or a temporary one)."""
    states = []
    try:
        for s in specs:
            if progress:
                progress("Opening %s" % s.get("label"), 0, 0)
            states.append(open_state(s))
        n = len(states)
        intervals = n - 1
        dirs: Dict[int, Tuple[int, str]] = {}          # record -> (parent, name), newest state wins
        direct_size = [dict() for _ in range(n)]       # parent record -> bytes of files directly in it
        direct_files = [dict() for _ in range(n)]
        counts = [dict() for _ in range(intervals)]    # parent -> [added, deleted, changed]
        pending = [dict() for _ in range(n)]           # base record without $DATA -> its parent
        ext_size = [dict() for _ in range(n)]          # base record -> size from its extension record
        resolved = [dict() for _ in range(n)]          # base record -> that size, once matched
        files: List[tuple] = []                        # (interval, change, parent, name, b_size, a_size, b_m, a_m, rec)
        total_records = max(st.size // st.rec for st in states) if states else 0
        first = 0
        t0 = time.time()
        while first < total_records:
            if is_cancelled and is_cancelled():
                break
            bufs = [st.chunk(first, chunk_records) for st in states]
            for i in range(chunk_records):
                recno = first + i
                if recno >= total_records:
                    break
                parsed = []
                for k, st in enumerate(states):
                    b = bufs[k]
                    off = i * st.rec
                    parsed.append(parse_record(b, off, st.rec) if off + st.rec <= len(b) else None)
                for k, p in enumerate(parsed):
                    if p is not None and p[0] == "ext":
                        base, size = p[1], p[2] or 0
                        parent = pending[k].pop(base, None)
                        if parent is not None:
                            direct_size[k][parent] = direct_size[k].get(parent, 0) + size
                            resolved[k][base] = size
                        else:
                            ext_size[k][base] = size
                        parsed[k] = None
                        continue
                    if p is None or not p[1]:
                        continue
                    if p[2]:
                        dirs[recno] = (p[3], p[4])
                    else:
                        size = p[5] or 0
                        if not p[7]:
                            if recno in ext_size[k]:
                                size = resolved[k][recno] = ext_size[k].pop(recno)
                            else:
                                pending[k][recno] = p[3]
                                size = 0
                        direct_size[k][p[3]] = direct_size[k].get(p[3], 0) + size
                        direct_files[k][p[3]] = direct_files[k].get(p[3], 0) + 1
                for k in range(intervals):
                    a, b = parsed[k], parsed[k + 1]
                    a_in = bool(a and a[1])
                    b_in = bool(b and b[1])
                    if not a_in and not b_in:
                        continue
                    if a_in and b_in and a[0] == b[0]:
                        if a[2] or (a[5] == b[5] and a[6] == b[6]):
                            continue
                        change, who = "changed", b
                    elif a_in and b_in:                 # reused: one deleted, one added
                        _count(counts[k], a[3], 1)
                        if len(files) < FILE_ROWS_CAP:
                            files.append((k, "deleted", a[3], a[4], a[5], None, a[6], None, recno, a[2]))
                        change, who = "added", b
                    elif b_in:
                        change, who = "added", b
                    else:
                        change, who = "deleted", a
                    idx = {"added": 0, "deleted": 1, "changed": 2}[change]
                    _count(counts[k], who[3], idx)
                    if len(files) < FILE_ROWS_CAP:
                        # before belongs to a deleted or changed file, after to an added or changed one
                        before = change in ("deleted", "changed")
                        after = change in ("added", "changed")
                        files.append((k, change, who[3], who[4],
                                      a[5] if before else None, b[5] if after else None,
                                      a[6] if before else None, b[6] if after else None, recno, who[2]))
            first += chunk_records
            if progress:
                el = time.time() - t0
                progress("Read %d of %d records in %d state(s)" % (min(first, total_records), total_records, n),
                         min(first, total_records), total_records)
        # A file whose $DATA sits in an extension record had only its $FILE_NAME size when its row
        # was written; the extension record, read since, holds the real one.
        for i, f in enumerate(files):
            k, rec = f[0], f[8]
            b_size = resolved[k].get(rec, f[4]) if f[4] is not None else None
            a_size = resolved[k + 1].get(rec, f[5]) if f[5] is not None else None
            if (b_size, a_size) != (f[4], f[5]):
                files[i] = f[:4] + (b_size, a_size) + f[6:]
        cancelled = bool(is_cancelled and is_cancelled())
        return _finish(specs, states, dirs, direct_size, direct_files, counts, files, scope, case_dir,
                       volume, cancelled)
    finally:
        for st in states:
            st.close()


def _count(d, parent, idx):
    c = d.get(parent)
    if c is None:
        c = d[parent] = [0, 0, 0]
    c[idx] += 1


ROOT = 5


def _paths(dirs: Dict[int, Tuple[int, str]]):
    cache = {ROOT: ""}

    def path(rec, depth=0):
        if rec in cache:
            return cache[rec]
        if depth > 64 or rec not in dirs:
            cache[rec] = None
            return None
        parent, name = dirs[rec]
        if parent == rec:
            cache[rec] = None
            return None
        p = path(parent, depth + 1)
        cache[rec] = None if p is None else (p + "\\" + name if p else name)
        return cache[rec]
    return path


def _pair_replacements(files, counts):
    """A file deleted and added again under the same folder and name in one interval was rewritten
    as a new file (save-to-temp-and-rename, as most programs save): one 'replaced' row, counted as
    changed, not as one deletion and one addition."""
    added = {}
    for i, f in enumerate(files):
        if f[1] == "added":
            added[(f[0], f[2], f[3].lower())] = i
    out, used = [], set()
    for i, f in enumerate(files):
        if f[1] != "deleted" or i in used:
            continue
        j = added.get((f[0], f[2], f[3].lower()))
        if j is None or j in used:
            continue
        used.update((i, j))
        a = files[j]
        out.append((f[0], "replaced", f[2], a[3], f[4], a[5], f[6], a[7], a[8], a[9]))
        c = counts[f[0]].get(f[2])
        if c is not None:
            c[0] -= 1
            c[1] -= 1
            c[2] += 1
    return [f for i, f in enumerate(files) if i not in used] + out


def _finish(specs, states, dirs, direct_size, direct_files, counts, files, scope, case_dir, volume, cancelled):
    files = _pair_replacements(files, counts)
    path = _paths(dirs)
    scope = (scope or "").replace("/", "\\").strip("\\")
    scope_l = scope.lower()

    def in_scope(p):
        return p is not None and (not scope or p.lower() == scope_l or p.lower().startswith(scope_l + "\\"))

    def ancestors(p):
        parts = p.split("\\") if p else []
        out = [""]
        for i in range(len(parts)):
            out.append("\\".join(parts[:i + 1]))
        return out

    n = len(states)
    folder_size = [dict() for _ in range(n)]
    folder_files = [dict() for _ in range(n)]
    for k in range(n):
        for parent, size in direct_size[k].items():
            p = path(parent)
            if p is None:
                continue
            nfiles = direct_files[k].get(parent, 0)
            for a in ancestors(p):
                folder_size[k][a] = folder_size[k].get(a, 0) + size
                folder_files[k][a] = folder_files[k].get(a, 0) + nfiles

    def keep(p):
        """Folders in scope, and the scope's own ancestors (so its total shows in context)."""
        return in_scope(p) or p == "" or (scope and scope_l.startswith(p.lower() + "\\"))
    folder_changes = [dict() for _ in range(n - 1)]
    for k, cmap in enumerate(counts):
        for parent, c in cmap.items():
            p = path(parent)
            if not in_scope(p):
                continue
            for a in ancestors(p):
                cur = folder_changes[k].setdefault(a, [0, 0, 0])
                cur[0] += c[0]
                cur[1] += c[1]
                cur[2] += c[2]

    run_id = "cmp-%s-%s" % (datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:6])
    db = os.path.join(case_dir, "Target_Artifacts", DB_NAME) if case_dir else os.path.join(
        os.environ.get("TEMP", "."), DB_NAME)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    con = sqlite3.connect(db)
    try:
        ensure_schema(con)
        con.execute("INSERT INTO shadow_compare_runs VALUES (?,?,?,?,?,?,?)",
                    (run_id, volume, scope, json.dumps([{k: v for k, v in s.items() if k != "stream"}
                                                        for s in specs], default=str),
                     datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "cancelled" if cancelled else "completed", len(files)))
        rows = []
        for k in range(n):
            for p, size in folder_size[k].items():
                if not keep(p):
                    continue
                rows.append((run_id, p, p.count("\\") + (1 if p else 0), k, size, folder_files[k].get(p, 0)))
        con.executemany("INSERT INTO shadow_compare_folders VALUES (?,?,?,?,?,?)", rows)
        con.executemany("INSERT INTO shadow_compare_folder_changes VALUES (?,?,?,?,?,?)",
                        [(run_id, p, k, c[0], c[1], c[2]) for k in range(n - 1)
                         for p, c in folder_changes[k].items()])
        frows = []
        for (k, change, parent, name, bs, as_, bm, am, recno, is_dir) in files:
            p = path(parent)
            if not in_scope(p):
                continue
            frows.append((run_id, k, (p + "\\" + name) if p else name, change, int(bool(is_dir)), bs, as_,
                          _ft_iso(bm) if bm else None, _ft_iso(am) if am else None, recno))
        con.executemany("INSERT INTO shadow_compare_files VALUES (?,?,?,?,?,?,?,?,?,?)", frows)
        con.commit()
    finally:
        con.close()
    totals = [folder_changes[k].get(scope if scope else "", [0, 0, 0]) for k in range(n - 1)]
    return {"run_id": run_id, "database": db, "states": [s.get("label") for s in specs],
            "intervals": totals, "files": len(frows), "cancelled": cancelled,
            "sizes": [folder_size[k].get(scope if scope else "", 0) for k in range(n)]}


def ensure_schema(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS shadow_compare_runs (
        run_id TEXT PRIMARY KEY, volume TEXT, scope TEXT, states TEXT, finished_utc TEXT,
        status TEXT, file_rows INTEGER);
    CREATE TABLE IF NOT EXISTS shadow_compare_folders (
        run_id TEXT, path TEXT, depth INTEGER, state INTEGER, size_bytes INTEGER, files INTEGER,
        PRIMARY KEY (run_id, path, state));
    CREATE TABLE IF NOT EXISTS shadow_compare_folder_changes (
        run_id TEXT, path TEXT, interval INTEGER, added INTEGER, deleted INTEGER, changed INTEGER,
        PRIMARY KEY (run_id, path, interval));
    CREATE TABLE IF NOT EXISTS shadow_compare_files (
        run_id TEXT, interval INTEGER, path TEXT, change TEXT, is_dir INTEGER, size_before INTEGER,
        size_after INTEGER, modified_before TEXT, modified_after TEXT, record INTEGER);
    CREATE INDEX IF NOT EXISTS shadow_compare_files_path ON shadow_compare_files (run_id, interval, path);
    """)
