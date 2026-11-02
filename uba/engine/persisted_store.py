"""
Persisted UBA event store — one stored answer per case.

``<case>/UBA/uba_events.db`` holds the events of the last full analysis plus
a ``meta`` table saying exactly what they were built from. The User Behavior
window, Eye's query_user_behavior and the Behavioural Engine all read it, so
they give one answer - and a case is analysed once, not once per window
opened (a full run reads every artifact database; up to about a minute on a
large case).

**Freshness.** The store is reused only while its stamp equals the stamp of
the case as it is now:

- ``format``          this module's layout version (bump with the schema)
- ``rules_version`` / ``rules_sha256`` / ``rules_count``  behavior_rules.json
- ``engine_code``     SHA-256 of the engine's own source, where readable
- ``sources``         every evidence database's size and mtime (and its
                      -wal file's): a re-parse changes them
- ``disabled_hash``   the rules turned off in Settings (rule_switches)
- ``user_rules_hash`` analyst-created rules (uba_user_rules.json, as loaded):
                      adding, editing or deleting one rebuilds. '' when there
                      are none. A database only a user rule reads (a file
                      outside UBA's logical names) joins ``sources``

Anything different means rebuild; nothing is patched in place. Times are UTC.

**Threads.** Loading copies the file into a private ``:memory:`` database
(sqlite3's backup API), the same store class the in-memory run produces, so
every query path is unchanged and no on-disk connection outlives the call
that opened it. Writing goes to a temporary file that replaces the old one
in a single rename, so a reader never sees half a store.

Headless: stdlib only.
"""

import glob
import hashlib
import json
import logging
import os
import sqlite3
import threading
from typing import Dict, Optional

from uba.engine.event_store import UBAEventStore
from uba.utils.db_access import DB_CANDIDATES, resolve_db_path

logger = logging.getLogger(__name__)

# 2: events carry user_rule (analyst-created rules).
FORMAT_VERSION = 2
STORE_DIRNAME = "UBA"
STORE_FILENAME = "uba_events.db"

# One builder at a time per store file: the UBA window and Eye can ask for the
# same case together, and the second should wait and then reuse, not run twice.
_PATH_LOCKS: Dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()

_STAMP_KEYS = ("format", "rules_version", "rules_sha256", "rules_count",
               "engine_code", "sources", "disabled_hash", "user_rules_hash")


def _utc_now_text() -> str:
    try:
        from utils.time_utils import get_current_utc, format_forensic_timestamp
        return format_forensic_timestamp(get_current_utc())
    except Exception:                        # pragma: no cover - headless host
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def store_path(artifacts_dir: str) -> str:
    """``<case>/UBA/uba_events.db`` for a case's Target_Artifacts folder.

    A folder not named Target_Artifacts is treated as the case itself (Eye
    falls back to the case directory when Target_Artifacts is missing).
    """
    base = os.path.abspath(artifacts_dir or ".")
    if os.path.basename(base.rstrip("\\/")).lower() == "target_artifacts":
        base = os.path.dirname(base.rstrip("\\/"))
    return os.path.join(base, STORE_DIRNAME, STORE_FILENAME)


def path_lock(path: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = _PATH_LOCKS[key] = threading.Lock()
        return lock


# --------------------------------------------------------------------- stamp
def _sha256_file(path: str) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


_CODE_HASH: Optional[str] = None


def engine_code_hash() -> str:
    """SHA-256 over the UBA engine's Python source, so a changed extractor
    rebuilds stores made by the old one. '' where the source is not on disk
    (a frozen build), and then rules_sha256 + format carry the stamp."""
    global _CODE_HASH
    if _CODE_HASH is not None:
        return _CODE_HASH
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # uba/
    files = []
    for pattern in ("engine/*.py", "engine/extractors/*.py", "utils/*.py",
                    "config/site_categories.json"):
        files.extend(sorted(glob.glob(os.path.join(root, *pattern.split("/")))))
    if not files:
        _CODE_HASH = ""
        return _CODE_HASH
    digest = hashlib.sha256()
    for path in files:
        digest.update(os.path.relpath(path, root).replace("\\", "/").encode("utf-8"))
        try:
            with open(path, "rb") as handle:
                digest.update(handle.read())
        except OSError:
            continue
    _CODE_HASH = digest.hexdigest()
    return _CODE_HASH


def _file_sig(path: str) -> Optional[list]:
    try:
        st = os.stat(path)
        return [st.st_size, round(st.st_mtime, 3)]
    except OSError:
        return None


def source_signatures(artifacts_dir: str, extra=()) -> dict:
    """{logical db: [size, mtime, wal size, wal mtime]} for every evidence
    database present. A database that appears or disappears changes it too.
    ``extra``: databases named by path that a user rule reads."""
    out = {}
    for logical in sorted(set(DB_CANDIDATES) | set(extra or ())):
        path = resolve_db_path(artifacts_dir, logical)
        if not path:
            continue
        sig = _file_sig(path) or [None, None]
        wal = _file_sig(path + "-wal") or [0, None]
        out[logical] = [os.path.relpath(path, artifacts_dir).replace("\\", "/")] + sig + wal
    return out


def compute_stamp(artifacts_dir: str, rules_config: dict, disabled_ids=(),
                  user_rules_hash: Optional[str] = None, extra_sources=()) -> dict:
    """What a store built now would be built from. ``rules_config`` may be
    the merged config (user_rules.merged_rules_config); its user rules are
    then read from it when ``user_rules_hash`` is not given."""
    from uba.engine import rule_switches
    rules_path = rules_config.get("path") or ""
    return {
        "format": FORMAT_VERSION,
        "rules_version": str(rules_config.get("version") or ""),
        "rules_sha256": _sha256_file(rules_path) if rules_path else "",
        "rules_count": len(rules_config.get("rules") or []),
        "engine_code": engine_code_hash(),
        "sources": source_signatures(artifacts_dir, extra_sources),
        "disabled_hash": rule_switches.disabled_hash(disabled_ids),
        "user_rules_hash": (rules_config.get("user_rules_hash") or ""
                            if user_rules_hash is None else user_rules_hash),
    }


def stamp_matches(stored: Optional[dict], current: dict) -> bool:
    if not stored:
        return False
    return all(_jsonable(stored.get(k)) == _jsonable(current.get(k)) for k in _STAMP_KEYS)


def stamp_differences(stored: Optional[dict], current: dict) -> list:
    """Which stamp keys differ - logged, so a rebuild says why it happened."""
    if not stored:
        return ["no store"]
    return [k for k in _STAMP_KEYS
            if _jsonable(stored.get(k)) != _jsonable(current.get(k))]


def _jsonable(value):
    # JSON round-trips tuples to lists; compare in the stored shape.
    return json.loads(json.dumps(value, default=str))


# --------------------------------------------------------------------- store
class PersistedStore:
    """Read and write one case's ``uba_events.db``."""

    def __init__(self, artifacts_dir: str, path: Optional[str] = None):
        self.artifacts_dir = artifacts_dir
        self.path = path or store_path(artifacts_dir)

    # ------------------------------------------------------------------ #
    def read_meta(self) -> Optional[dict]:
        """The stored meta (stamp, built_at, coverage, stats, sessions...), or
        None when there is no readable store."""
        if not os.path.isfile(self.path):
            return None
        try:
            conn = sqlite3.connect("file:{}?mode=ro".format(
                self.path.replace("\\", "/")), uri=True, timeout=10)
        except sqlite3.Error:
            return None
        try:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
            return {k: json.loads(v) for k, v in rows}
        except (sqlite3.Error, ValueError) as e:
            logger.warning("UBA: stored analysis unreadable (%s): %s", self.path, e)
            return None
        finally:
            conn.close()

    def is_fresh(self, stamp: dict) -> bool:
        meta = self.read_meta()
        return bool(meta) and stamp_matches(meta.get("stamp"), stamp)

    def load(self, stamp: Optional[dict] = None):
        """(UBAEventStore, meta) copied into memory, or (None, meta/None) when
        the store is missing, unreadable or - given ``stamp`` - stale."""
        meta = self.read_meta()
        if not meta:
            return None, None
        if stamp is not None and not stamp_matches(meta.get("stamp"), stamp):
            logger.info("UBA: stored analysis is stale (%s) - %s",
                        ", ".join(stamp_differences(meta.get("stamp"), stamp)), self.path)
            return None, meta
        store = UBAEventStore(create_schema=False)
        try:
            src = sqlite3.connect("file:{}?mode=ro".format(
                self.path.replace("\\", "/")), uri=True, timeout=10)
            try:
                src.backup(store.conn)
            finally:
                src.close()
            store.conn.execute("DROP TABLE IF EXISTS meta")
            store.conn.commit()
        except sqlite3.Error as e:
            logger.warning("UBA: stored analysis could not be loaded (%s): %s", self.path, e)
            store.conn.close()
            return None, meta
        return store, meta

    def _event_count(self):
        try:
            conn = sqlite3.connect("file:" + os.path.abspath(self.path).replace("\\", "/") + "?mode=ro", uri=True)
            try:
                return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error:
            return None

    def _record_custody(self, stamp: dict, extra: dict):
        """The stored analysis in the case's custody ledger: its SHA-256, what
        it was built from (the stamp's sources and rule versions). Behaviour
        Wings, behaviour context and Eye read it, so the version they read has
        to be provable."""
        try:
            from utils import custody
            case_dir = os.path.dirname(os.path.dirname(os.path.abspath(self.path)))
            custody.ledger(case_dir, "user behaviour analysis built",
                           path=os.path.abspath(self.path),
                           sha256=custody.sha256_file(self.path)[0],
                           rules_version=(stamp or {}).get("rules_version"),
                           rules_sha256=(stamp or {}).get("rules_sha256"),
                           sources=sorted(((stamp or {}).get("sources") or {}).keys()),
                           events=self._event_count())
        except Exception as e:
            logger.debug("UBA: custody entry not written: %s", e)

    def save(self, store: UBAEventStore, stamp: dict, **extra) -> bool:
        """Write ``store`` plus meta (stamp, built_at_utc, and every ``extra``
        value as JSON) to the file, replacing any older one atomically."""
        folder = os.path.dirname(self.path)
        tmp = self.path + ".tmp"
        try:
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(tmp):
                os.remove(tmp)
            dst = sqlite3.connect(tmp)
            try:
                store.conn.backup(dst)
                dst.execute("CREATE TABLE IF NOT EXISTS meta "
                            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                meta = {"stamp": stamp, "built_at_utc": _utc_now_text()}
                meta.update(extra)
                dst.executemany(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    [(k, json.dumps(v, default=str)) for k, v in meta.items()])
                dst.commit()
            finally:
                dst.close()
            os.replace(tmp, self.path)
            logger.info("UBA: analysis stored at %s", self.path)
            self._record_custody(stamp, extra)
            return True
        except (sqlite3.Error, OSError) as e:
            # A case folder that cannot be written (read-only media) still gets
            # its answer - from memory, every time.
            logger.warning("UBA: analysis could not be stored at %s: %s", self.path, e)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False
