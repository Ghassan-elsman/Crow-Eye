"""Chain of custody for a live collection.

A live collection runs on the machine under examination, so what Crow-Eye
read, how it read it, and what it changed on that machine are part of the
evidence. Until now none of it was written down: copies were made and never
hashed against their source, shadow copies were created and left behind, and
the only record of a run was a log written for debugging.

One record per run, written to ``<case>/logs/custody_<run id>.json`` with a
``.sha256`` beside it, holding:

  who and where   examiner (OS account), host, OS build, tool and version,
                  command line and options - every time in UTC
  per source      path, size, the MACB times read BEFORE the copy, how it was
                  read (standard / vss + snapshot id and creation time / raw /
                  live-hive export), SHA-256 of the source where it can be read
                  as a stream, SHA-256 of the copy, and whether the two agree
  failures        what could not be read, and why
  footprint       every change Crow-Eye made to the target: shadow copies it
                  created and deleted, services it started, processes it ran,
                  files it wrote outside the case folder
  warnings        e.g. the case folder sits on the target's own system drive

Records are never overwritten - each run gets its own file - and the JSON is
hashed when it is closed, so a later edit shows.

Deep code (the VSS manager, a parser that shells out) reports into the record
that is open, through the module functions ``footprint()`` / ``note_process()``
/ ``warn()``; they do nothing when no collection is running, so callers never
need to know whether one is. Several runs can be open at once (two QThreads):
each thread reports into its own run (``active()``).

Besides the per-run records, every case keeps ONE ledger of everything done
to it - ``<case>/logs/custody_ledger.jsonl`` - one JSON line per event (case
opened, run started / ended with its record's SHA-256, export written, evidence
imported, settings changed, a database rewritten), each line carrying the
SHA-256 of the line before it. Editing, removing or re-ordering any line
breaks the chain, and a run record that is rewritten or deleted no longer
matches the hash its "run ended" line holds: ``verify_ledger()``.
"""
import datetime as _dt
import getpass
import hashlib
import json
import os
import platform
import re
import socket
import sys
import threading
import time
import uuid

_LOCK = threading.RLock()
_ACTIVE = None            # the most recently opened run (see active())
_OPEN = {}                # run_id -> open CustodyRecord, this process
_THREAD = threading.local()

CHUNK = 1024 * 1024

LEDGER_NAME = "custody_ledger.jsonl"
GENESIS = "0" * 64
_LEDGER_LOCK = threading.RLock()
_CASE_DIR = None          # the case the GUI has open (set_case)

# Settings keys that are never written to the ledger, even as "changed".
_SECRET_WORDS = ("key", "token", "secret", "password", "credential", "auth")


def _utc_now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _utc_from_epoch(ts):
    try:
        return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def sha256_file(path):
    """(hex digest, bytes read), or (None, error text) when it cannot be read."""
    h = hashlib.sha256()
    n = 0
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                h.update(chunk)
                n += len(chunk)
    except OSError as e:
        return None, "%s: %s" % (type(e).__name__, e)
    return h.hexdigest(), n


def file_times(path):
    """Size and MACB times (UTC) from the file system, read without opening it.

    On Windows ``st_ctime`` is the creation time; elsewhere it is the inode
    change time, and ``st_birthtime`` is used where the platform has it.
    """
    try:
        st = os.stat(path)
    except OSError as e:
        return {"error": "%s: %s" % (type(e).__name__, e)}
    born = getattr(st, "st_birthtime", None)
    if born is None and os.name == "nt":
        born = st.st_ctime
    out = {
        "size": st.st_size,
        "modified_utc": _utc_from_epoch(st.st_mtime),
        "accessed_utc": _utc_from_epoch(st.st_atime),
        "created_utc": _utc_from_epoch(born) if born is not None else None,
    }
    if os.name != "nt":
        out["changed_utc"] = _utc_from_epoch(st.st_ctime)
    return out


def _tool_version():
    main = sys.modules.get("__main__")
    v = getattr(main, "__version__", None)
    if v:
        return str(v)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(here, "Crow Eye.py"), encoding="utf-8", errors="replace") as fh:
            for _ in range(200):
                m = re.match(r'__version__\s*=\s*"([^"]+)"', fh.readline())
                if m:
                    return m.group(1)
    except OSError:
        pass
    return "unknown"


def _os_build():
    info = {"platform": platform.platform(), "release": platform.release(),
            "version": platform.version(), "machine": platform.machine()}
    if hasattr(sys, "getwindowsversion"):
        w = sys.getwindowsversion()
        info["windows_build"] = "%d.%d.%d" % (w.major, w.minor, w.build)
    return info


_LIBRARIES = ("python-registry", "dissect.target", "dissect.regf", "dissect.ntfs",
              "dissect.esedb", "dissect.evtx", "python-evtx", "pywin32", "PyQt5",
              "libesedb-python", "pyesedb", "pyscca", "LnkParse3", "zstandard", "pyewf",
              "libewf-python", "pytsk3")


def _environment():
    """What shapes how a value was read and shown: time zone, locale, and the
    versions of the libraries that decode the evidence. Times in a record are
    UTC; the zone is here so a reader can relate them to the examiner's clock."""
    env = {}
    try:
        dst = time.daylight and time.localtime().tm_isdst > 0
        offset = -(time.altzone if dst else time.timezone)
        env["timezone"] = time.tzname[1 if dst else 0]
        env["utc_offset"] = "%+03d:%02d" % (offset // 3600, abs(offset) % 3600 // 60)
    except Exception:
        pass
    try:
        import locale
        env["locale"] = ".".join(x for x in locale.getlocale() if x) or None
    except Exception:
        pass
    versions = {}
    try:
        import importlib.metadata as _md
        for name in _LIBRARIES:
            try:
                versions[name] = _md.version(name)
            except Exception:
                pass
    except Exception:
        pass
    try:
        from PyQt5 import QtCore
        versions["Qt"] = QtCore.QT_VERSION_STR
    except Exception:
        pass
    env["libraries"] = versions
    return env


def _examiner():
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def _is_admin():
    try:
        if os.name == "nt":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return None


def system_drive():
    """The target's system drive, e.g. ``C:`` (None off Windows)."""
    if os.name != "nt":
        return None
    return (os.environ.get("SystemDrive") or "C:").upper()


def case_on_system_drive(case_dir):
    """True when the case folder sits on the drive being examined.

    Every byte Crow-Eye writes there can overwrite unallocated space that still
    holds deleted evidence. Not blocking - a triage on the examiner's own
    machine is legitimate - but it belongs in the record.
    """
    drive = system_drive()
    if not drive or not case_dir:
        return False
    return os.path.splitdrive(os.path.abspath(case_dir))[0].upper() == drive


class CustodyRecord:
    """One collection run. Thread-safe; closed exactly once."""

    def __init__(self, case_dir, kind, options=None, output_dir=None, run_id=None,
                 journal=False, role="collector"):
        started = _dt.datetime.now(_dt.timezone.utc)
        self.run_id = run_id or new_run_id(started)
        self.case_dir = os.path.abspath(case_dir) if case_dir else os.getcwd()
        self.closed_path = None
        self._lock = threading.RLock()
        self.role = role
        self._journal = None
        examiner = _examiner()
        self.data = {
            "format": "crow-eye-custody/1",
            "run_id": self.run_id,
            "kind": kind,
            "started_utc": started.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "finished_utc": None,
            "status": "running",
            "examiner": examiner,
            "elevated": _is_admin(),
            "host": {"name": socket.gethostname(), "fqdn": socket.getfqdn()},
            "os": _os_build(),
            "tool": {"name": "Crow-Eye", "version": _tool_version(),
                     "python": sys.version.split()[0],
                     "frozen": bool(getattr(sys, "frozen", False))},
            "command_line": list(sys.argv),
            "options": dict(options or {}),
            "case_dir": self.case_dir,
            "case_name": os.path.basename(self.case_dir.rstrip("\\/")),
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "environment": _environment(),
            "sources": [],
            "failures": [],
            "footprint": [],
            "shadow_copies": [],
            "warnings": [],
            "outputs": [],
        }
        if journal:
            self._open_journal(header=True)
        if case_on_system_drive(self.case_dir):
            self.warn("The case folder is on %s, the drive being examined. Writing there can "
                      "overwrite unallocated clusters that still hold deleted evidence; an "
                      "external or network drive avoids it." % system_drive())

    # --- what was read --------------------------------------------------------
    def add_source(self, source, copy=None, method="standard", times=None,
                   source_sha256=None, read_from=None, shadow_copy_id=None,
                   shadow_copy_created_utc=None, note=None, hash_source=True,
                   copy_sha256=None):
        """Record one source file and, when it was copied, verify the copy.

        ``times`` should be ``file_times(source)`` taken BEFORE the copy; when
        it is not given it is read now. ``read_from`` is where the bytes really
        came from (the shadow-copy path for VSS); the source hash is taken from
        there when it is a stream, because the live file is the one that was
        locked.
        """
        entry = {
            "source": source,
            "method": method,
            "times": times if times is not None else file_times(source),
            "recorded_utc": _utc_now(),
        }
        if read_from and read_from != source:
            entry["read_from"] = read_from
        if shadow_copy_id:
            entry["shadow_copy_id"] = shadow_copy_id
            entry["shadow_copy_created_utc"] = shadow_copy_created_utc
        if note:
            entry["note"] = note
        if source_sha256 is None and hash_source and method != "raw_disk":
            digest, info = sha256_file(read_from or source)
            if digest:
                source_sha256 = digest
            else:
                entry["source_hash_error"] = info
        if source_sha256:
            entry["source_sha256"] = source_sha256
        if copy:
            entry["copy"] = copy
            if copy_sha256:
                # Already hashed by the validator: one read of the copy, not two.
                digest = copy_sha256
                try:
                    entry["copy_size"] = os.path.getsize(copy)
                except OSError:
                    pass
            else:
                digest, info = sha256_file(copy)
                if digest:
                    entry["copy_size"] = info
                else:
                    entry["copy_hash_error"] = info
            if digest:
                entry["copy_sha256"] = digest
            if source_sha256 and digest:
                entry["verified"] = source_sha256 == digest
                if not entry["verified"]:
                    entry["mismatch"] = ("The copy's SHA-256 differs from the source's. For a "
                                         "file in use (a log being written) the source can "
                                         "change between the two reads; otherwise the copy "
                                         "is not faithful.")
            else:
                # Raw-disk reads and files locked against a second read have no
                # independent source hash: say so rather than claim a match.
                entry["verified"] = None
        self._append("sources", entry)
        return entry

    def inventory(self, patterns, hash_limit=256 * 1024 * 1024, max_files=20000, should_stop=None):
        """Record files a parse is about to read in place, before it reads them.

        A live parse opens the evidence where it lies instead of copying it, so
        there is no copy to verify - but the size, times and (where the file is
        readable and not huge) SHA-256 taken before the parse are what tie a
        parsed row back to the bytes it came from. Locked files are listed with
        the reason they could not be hashed: that is a fact about the run too.
        """
        import glob as _glob
        seen, count = set(), 0
        for pattern in patterns:
            for path in sorted(_glob.glob(pattern)):
                key = os.path.normcase(path)
                if key in seen or not os.path.isfile(path):
                    continue
                seen.add(key)
                if should_stop is not None and should_stop():
                    self.warn("Source inventory stopped: the run was cancelled.")
                    return count
                count += 1
                if count > max_files:
                    self.warn("Source inventory stopped at %d files." % max_files)
                    return count - 1
                times = file_times(path)
                big = (times.get("size") or 0) > hash_limit
                self.add_source(path, method="in-place read", times=times, hash_source=not big,
                                note="not hashed: larger than %d MB" % (hash_limit // 2**20) if big else None)
        return count

    def add_failure(self, source, reason, method=None, **extra):
        item = {"source": source, "reason": str(reason)[:2000], "method": method,
                "recorded_utc": _utc_now()}
        item.update({k: v for k, v in extra.items() if v is not None})
        self._append("failures", item)

    # --- what was written -----------------------------------------------------
    def add_output(self, path, kind="database", hash_limit=None, note=None):
        """Record one file the run produced: size, modified time, SHA-256.

        What the GUI, Eye and a report later read comes from these files; the
        hash taken as the run closes is what ties them back to this run.
        """
        entry = {"path": os.path.abspath(path), "kind": kind, "recorded_utc": _utc_now()}
        t = file_times(path)
        if "error" in t:
            entry["error"] = t["error"]
        else:
            entry["size"] = t.get("size")
            entry["modified_utc"] = t.get("modified_utc")
            if hash_limit is not None and (t.get("size") or 0) > hash_limit:
                entry["note"] = "not hashed: larger than %d MB" % (hash_limit // 2**20)
            else:
                digest, info = sha256_file(path)
                if digest:
                    entry["sha256"] = digest
                else:
                    entry["hash_error"] = info
        if note:
            entry["note"] = (entry.get("note", "") + "; " if entry.get("note") else "") + note
        self._append("outputs", entry)
        return entry

    def record_outputs(self, folder=None, patterns=("*.db", "*.db-wal", "*.sqlite"),
                       should_stop=None, progress=None, since=None):
        """Hash every database the run left in ``folder`` (default: output_dir).

        A ``-wal`` file is recorded as a file of its own rather than folded in
        with a checkpoint: checkpointing would rewrite the database while the
        record claims to describe it. ``since`` (epoch seconds): only files
        modified from then on - what a single-artifact run wrote, not the
        whole case. Returns the number recorded.
        """
        import glob as _glob
        folder = folder or self.data.get("output_dir")
        if not folder or not os.path.isdir(folder):
            return 0
        n = 0
        for pattern in patterns:
            for path in sorted(_glob.glob(os.path.join(folder, pattern))):
                if since is not None:
                    try:
                        if os.path.getmtime(path) < since - 2:
                            continue
                    except OSError:
                        continue
                if should_stop is not None and should_stop():
                    self.warn("Output hashing stopped: the run was cancelled.")
                    return n
                if progress is not None:
                    try:
                        progress(path)
                    except Exception:
                        pass
                self.add_output(path, kind="wal" if path.endswith("-wal") else "database")
                n += 1
        return n

    # --- what was changed -----------------------------------------------------
    def footprint(self, kind, detail, **extra):
        item = {"kind": kind, "detail": detail, "recorded_utc": _utc_now()}
        item.update({k: v for k, v in extra.items() if v is not None})
        self._append("footprint", item)
        return item

    def shadow_copy(self, action, shadow_copy_id=None, volume=None, created_utc=None,
                    command=None, ok=True, detail=None):
        """``action``: created / deleted / used-existing / delete-failed."""
        item = {"action": action, "shadow_copy_id": shadow_copy_id, "volume": volume,
                "created_utc": created_utc, "command": command, "ok": ok,
                "detail": detail, "recorded_utc": _utc_now()}
        self._append("shadow_copies", {k: v for k, v in item.items() if v is not None})

    def warn(self, message):
        with self._lock:
            if message in self.data["warnings"]:
                return
        self._append("warnings", message)

    # --- the journal: one JSON line per entry, flushed as it is made -----------
    # A live parse runs in several processes. Each writes its entries to its own
    # file under logs/custody_parts/<run>/ the moment it makes them; the
    # collector merges them before it closes the record, and if the run is
    # killed the record is rebuilt from them (salvage). Without this, what a
    # pool worker read - and the shadow copies it used - never reached the
    # run's record.
    def _parts_dir(self):
        return os.path.join(self.case_dir, "logs", "custody_parts", self.run_id)

    def _open_journal(self, header=False):
        try:
            d = self._parts_dir()
            os.makedirs(d, exist_ok=True)
            self._journal_path = os.path.join(d, "%s-%d.jsonl" % (self.role, os.getpid()))
            self._journal = open(self._journal_path, "a", encoding="utf-8")
            if header:
                head = {k: v for k, v in self.data.items() if not isinstance(v, list)}
                self._write_line({"section": "header", "item": head})
        except OSError:
            self._journal = None

    def _write_line(self, obj):
        if self._journal is None:
            return
        try:
            self._journal.write(json.dumps(obj, default=str) + "\n")
            self._journal.flush()
        except (OSError, ValueError):
            pass

    def _append(self, section, item):
        with self._lock:
            self.data[section].append(item)
            self._write_line({"section": section, "item": item})

    def note_purpose(self, text, purpose, returncode):
        """A process entry gained its purpose / return code (see note_process)."""
        self._write_line({"section": "process_purpose",
                          "item": {"detail": text, "purpose": purpose, "returncode": returncode}})

    def merge_fragments(self):
        """Fold in what the other processes of this run journaled. Returns the count."""
        d = self._parts_dir()
        own = getattr(self, "_journal_path", None)
        merged = 0
        if not os.path.isdir(d):
            return 0
        for name in sorted(os.listdir(d)):
            path = os.path.join(d, name)
            if not name.endswith(".jsonl") or (own and os.path.normcase(path) == os.path.normcase(own)):
                continue
            tag = name[:-6]
            purposes = []
            try:
                with open(path, encoding="utf-8") as fh:
                    lines = fh.readlines()
            except OSError as e:
                self.warn("Custody fragment %s unreadable: %s" % (name, e))
                continue
            for line in lines:
                try:
                    obj = json.loads(line)
                except ValueError:
                    self.warn("Custody fragment %s has a damaged line (the process was ended "
                              "while writing it)." % name)
                    continue
                section, item = obj.get("section"), obj.get("item")
                if section == "process_purpose":
                    purposes.append(item)
                    continue
                if section not in ("sources", "failures", "footprint", "shadow_copies", "warnings",
                                   "outputs"):
                    continue
                if section == "warnings":
                    self.warn(item)
                else:
                    item = dict(item)
                    item["process"] = tag
                    with self._lock:
                        self.data[section].append(item)
                merged += 1
            with self._lock:
                for p in purposes:
                    for it in reversed(self.data["footprint"]):
                        if (it.get("process") == tag and it.get("kind") == "process"
                                and it.get("detail") == p.get("detail") and "purpose" not in it):
                            if p.get("purpose"):
                                it["purpose"] = p["purpose"]
                            if p.get("returncode") is not None:
                                it["returncode"] = p["returncode"]
                            break
        return merged

    def _drop_parts(self):
        import shutil
        try:
            if self._journal is not None:
                self._journal.close()
        except OSError:
            pass
        self._journal = None
        shutil.rmtree(self._parts_dir(), ignore_errors=True)

    # --- closing --------------------------------------------------------------
    def summary(self):
        with self._lock:
            s = self.data["sources"]
            return {
                "sources": len(s),
                "copies_verified": sum(1 for e in s if e.get("verified") is True),
                "copies_mismatched": sum(1 for e in s if e.get("verified") is False),
                "copies_unverifiable": sum(1 for e in s if "copy" in e and e.get("verified") is None),
                "failures": len(self.data["failures"]),
                "footprint_items": len(self.data["footprint"]),
                "shadow_copies_created": sum(1 for v in self.data["shadow_copies"]
                                             if v.get("action") == "created"),
                "shadow_copies_left_behind": _left_behind(self.data["shadow_copies"]),
                "outputs": len(self.data.get("outputs") or []),
                # Rows this run added to the case vs rows already there (a
                # re-parse adds only what is new) - summed over its artifacts.
                "rows_new": sum(int(a.get("inserted") or 0)
                                for a in self.data.get("artifacts") or [] if isinstance(a, dict)),
                "rows_already_present": sum(int(a.get("duplicates") or 0)
                                            for a in self.data.get("artifacts") or []
                                            if isinstance(a, dict)),
                # Indexes added to case databases (a change to the case).
                "indexes_created": sum(len(a.get("indexes_created") or [])
                                       for a in self.data.get("artifacts") or []
                                       if isinstance(a, dict)),
            }

    def close(self, status="completed"):
        """Write the record and its hash. Returns the JSON path (idempotent)."""
        with self._lock:
            if self.closed_path:
                return self.closed_path
            self.merge_fragments()
            # What the caller did after the run's own processes stopped (the
            # GUI deleting a killed run's snapshot) comes after what they did.
            for ev in getattr(self, "_after_merge", None) or ():
                try:
                    self.shadow_copy(**ev)
                except TypeError:
                    pass
            self.data["finished_utc"] = _utc_now()
            self.data["status"] = status
            self.data["summary"] = self.summary()
            logs = os.path.join(self.case_dir, "logs")
            os.makedirs(logs, exist_ok=True)
            path = os.path.join(logs, "custody_%s.json" % self.run_id)
            blob = (json.dumps(self.data, indent=1, sort_keys=False, default=str) + "\n").encode("utf-8")
            with open(path, "xb") as fh:          # never overwrite an earlier run
                fh.write(blob)
            digest = hashlib.sha256(blob).hexdigest()
            with open(path + ".sha256", "w", encoding="ascii", newline="\n") as fh:
                fh.write("%s  %s\n" % (digest, os.path.basename(path)))
            self.closed_path = path
            # Folded into the record, which is now hashed: the parts are spent.
            self._drop_parts()
        # Into the case's ledger, with the record's hash: a record rewritten
        # or deleted later no longer matches this line (verify_ledger).
        # Identity indexes the run added to case databases (re-parse checks
        # need them): not evidence, but a change to the case, so it is said.
        added = [m for a in self.data.get("artifacts") or [] if isinstance(a, dict)
                 for m in (a.get("indexes_created") or [])]
        if added:
            ledger(self.case_dir, "database changed", run_id=self.run_id,
                   what="identity indexes added for re-parse checks", indexes=added)
        ledger(self.case_dir, "run ended", run_id=self.run_id, kind=self.data.get("kind"),
               status=status, record=os.path.basename(path), record_sha256=digest,
               summary=self.data.get("summary"))
        return path


class CustodyFragment(CustodyRecord):
    """A pool worker's share of a run: the same API, journal only.

    It never writes a record of its own - the collector merges the fragment
    into the run's record (or salvage() does, if the run was killed).
    """

    def __init__(self, case_dir, run_id, role="worker"):
        self.run_id = run_id
        self.case_dir = os.path.abspath(case_dir)
        self.closed_path = None
        self._lock = threading.RLock()
        self.role = role
        self._journal = None
        self.data = {"sources": [], "failures": [], "footprint": [], "shadow_copies": [],
                     "warnings": [], "outputs": []}
        self._open_journal(header=False)

    def merge_fragments(self):
        return 0

    def close(self, status="completed"):
        try:
            if self._journal is not None:
                self._journal.close()
        except OSError:
            pass
        self._journal = None
        return None


def new_run_id(started=None):
    """A run id: UTC start time + a random suffix. The GUI makes it, so the
    collector, its workers and a salvage after a kill all name the same run."""
    started = started or _dt.datetime.now(_dt.timezone.utc)
    return "%s_%s" % (started.strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:6])


def salvage(case_dir, run_id, status="interrupted", shadow_copy_events=()):
    """Rebuild and close a run's record from its journals alone.

    For a run that never closed its record: the collector was killed, or the
    machine went down mid-parse. Returns the record path, or None when there is
    nothing to salvage (or the record already exists). ``shadow_copy_events``
    are what the caller did about the run's snapshots before salvaging (the
    GUI deletes them first), as shadow_copy() keyword dicts.
    """
    case_dir = os.path.abspath(case_dir)
    if os.path.exists(os.path.join(case_dir, "logs", "custody_%s.json" % run_id)):
        return None
    parts = os.path.join(case_dir, "logs", "custody_parts", run_id)
    if not os.path.isdir(parts):
        return None
    header = None
    for name in sorted(os.listdir(parts)):
        if name.startswith("collector-") and name.endswith(".jsonl"):
            try:
                with open(os.path.join(parts, name), encoding="utf-8") as fh:
                    first = json.loads(fh.readline())
                if first.get("section") == "header":
                    header = first.get("item")
            except (OSError, ValueError):
                pass
    rec = CustodyRecord(case_dir, (header or {}).get("kind", "live parse"), run_id=run_id)
    if header:
        for k, v in header.items():
            if k not in ("status", "finished_utc"):
                rec.data[k] = v
    rec.warn("This record was rebuilt from the run's journals: the run ended without "
             "closing it (%s)." % status)
    rec._after_merge = list(shadow_copy_events or ())
    return rec.close(status)


def salvage_orphans(case_dir):
    """Salvage every run in this case whose record was never written. Returns paths."""
    root = os.path.join(os.path.abspath(case_dir), "logs", "custody_parts")
    out = []
    if os.path.isdir(root):
        for run_id in sorted(os.listdir(root)):
            if run_id in _OPEN:
                continue                      # still running in this process
            try:
                p = salvage(case_dir, run_id, "interrupted")
            except Exception:
                p = None
            if p:
                out.append(p)
    return out


def _left_behind(events):
    created = [e.get("shadow_copy_id") for e in events if e.get("action") == "created"]
    deleted = {e.get("shadow_copy_id") for e in events if e.get("action") == "deleted" and e.get("ok", True)}
    return [c for c in created if c and c not in deleted]


def live_source_patterns(partition="C:"):
    """The evidence files a live parse reads in place, as globs on ``partition``."""
    root = partition.rstrip("\\/") + os.sep
    j = lambda *p: os.path.join(root, *p)
    users = j("Users", "*")
    roaming = os.path.join(users, "AppData", "Roaming")
    local = os.path.join(users, "AppData", "Local")
    config = j("Windows", "System32", "config")
    return [
        os.path.join(config, "SYSTEM"),
        os.path.join(config, "SOFTWARE"),
        os.path.join(config, "SAM"),
        os.path.join(config, "SECURITY"),
        os.path.join(config, "DEFAULT"),
        # transaction logs: replayed into the hive before it is parsed
        os.path.join(config, "*.LOG1"),
        os.path.join(config, "*.LOG2"),
        os.path.join(users, "NTUSER.DAT"),
        os.path.join(users, "ntuser.dat.LOG1"),
        os.path.join(users, "ntuser.dat.LOG2"),
        os.path.join(local, "Microsoft", "Windows", "UsrClass.dat"),
        os.path.join(local, "Microsoft", "Windows", "UsrClass.dat.LOG1"),
        os.path.join(local, "Microsoft", "Windows", "UsrClass.dat.LOG2"),
        # the service accounts' own hives
        j("Windows", "ServiceProfiles", "*", "NTUSER.DAT"),
        j("Windows", "AppCompat", "Programs", "Amcache.hve"),
        j("Windows", "AppCompat", "Programs", "Amcache.hve.LOG1"),
        j("Windows", "AppCompat", "Programs", "Amcache.hve.LOG2"),
        j("Windows", "System32", "sru", "SRUDB.dat"),
        j("Windows", "Prefetch", "*.pf"),
        j("Windows", "System32", "winevt", "Logs", "*.evtx"),
        os.path.join(roaming, "Microsoft", "Windows", "Recent", "*.lnk"),
        os.path.join(roaming, "Microsoft", "Windows", "Recent", "AutomaticDestinations", "*"),
        os.path.join(roaming, "Microsoft", "Windows", "Recent", "CustomDestinations", "*"),
        # shortcuts the LNK parser walks besides Recent
        os.path.join(users, "Desktop", "*.lnk"),
        os.path.join(roaming, "Microsoft", "Windows", "Start Menu", "Programs", "*.lnk"),
        j("ProgramData", "Microsoft", "Windows", "Start Menu", "Programs", "*.lnk"),
        # browser profiles (Chromium family and Firefox)
        os.path.join(local, "Google", "Chrome", "User Data", "*", "History"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "*", "History"),
        os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "*", "History"),
        os.path.join(roaming, "Mozilla", "Firefox", "Profiles", "*", "places.sqlite"),
        # the Recycle Bin: $I metadata and the $R content it describes
        j("$Recycle.Bin", "*", "$I*"),
        j("$Recycle.Bin", "*", "$R*"),
    ]


def verify_record(path):
    """True when the JSON still matches the hash written beside it."""
    try:
        with open(path + ".sha256", encoding="ascii") as fh:
            want = fh.read().split()[0]
        digest, _ = sha256_file(path)
        return digest == want
    except (OSError, IndexError):
        return False


# --- the case ledger ------------------------------------------------------------
def set_case(case_dir):
    """The case the GUI has open: where ledger() writes when no case is named."""
    global _CASE_DIR
    _CASE_DIR = os.path.abspath(case_dir) if case_dir else None


def current_case():
    return _CASE_DIR


def ledger_path(case_dir):
    return os.path.join(os.path.abspath(case_dir), "logs", LEDGER_NAME)


class _FileLock:
    """A lock other processes respect (the collector writes the ledger too).

    Waits up to ``timeout`` seconds; after that the event is written anyway -
    losing a custody event would be worse than a rare out-of-order line, which
    verify_ledger() reports rather than hides.
    """

    def __init__(self, path, timeout=10.0):
        self.path, self.timeout, self.fh, self.locked = path, timeout, None, False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fh = open(self.path, "a+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.locked = True
                return self
            except OSError:
                if time.monotonic() > deadline:
                    return self
                time.sleep(0.02)

    def __exit__(self, *exc):
        try:
            if self.locked:
                if os.name == "nt":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self.fh.close()
        return False


def _entry_hash(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _last_ledger_entry(path):
    """The last line that parses, read from the end of the file."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = min(size, 65536)
            while True:
                fh.seek(size - block)
                lines = fh.read(block).splitlines()
                for raw in reversed(lines):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except ValueError:
                        continue
                if block >= size:
                    return None
                block = min(size, block * 4)
    except OSError:
        return None


def _clean(value, depth=0):
    """JSON-safe, size-bounded copy of an event's fields."""
    if depth > 6:
        return str(value)[:200]
    if isinstance(value, dict):
        return {str(k): _clean(v, depth + 1) for k, v in list(value.items())[:200]}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v, depth + 1) for v in list(value)[:500]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value[:4000] if isinstance(value, str) else value
    return str(value)[:4000]


def ledger(case_dir, event, **fields):
    """Append one event to the case's ledger. Never raises; returns the entry.

    ``case_dir`` None means the case the GUI has open (set_case). Each line
    holds the SHA-256 of the line before it (``prev``) and of itself
    (``hash``), so the file is a chain: verify_ledger() walks it.
    """
    case_dir = case_dir or _CASE_DIR
    if not case_dir:
        return None
    try:
        path = ledger_path(case_dir)
        with _LEDGER_LOCK, _FileLock(path + ".lock"):
            last = _last_ledger_entry(path) if os.path.exists(path) else None
            entry = {
                "seq": (int(last.get("seq") or 0) + 1) if last else 1,
                "utc": _utc_now(),
                "event": str(event),
                "examiner": _examiner(),
                "host": socket.gethostname(),
                "pid": os.getpid(),
                "fields": _clean(fields),
                "prev": (last or {}).get("hash") or GENESIS,
            }
            entry["hash"] = _entry_hash(entry)
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
                fh.flush()
        return entry
    except Exception:
        return None


def read_ledger(case_dir):
    """Every entry, in file order; a line that does not parse is returned as
    {"damaged": <text>} so the viewer can show it."""
    out = []
    path = ledger_path(case_dir)
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"damaged": line[:500]})
    return out


def verify_ledger(case_dir):
    """Walk the chain and cross-check the run records against it.

    Returns {"ok", "entries", "problems": [...], "notes": [...], "head"}.
    A problem is anything that means the trail was altered: a line whose
    hash does not match, a broken link or a gap in the sequence (a line
    edited, removed or moved), a run record whose SHA-256 differs from the
    one its "run ended" line holds, a record the ledger names that is gone,
    or a record pointing at a ledger line that is no longer there (the
    ledger was cut short). Notes are facts that are not tampering - a record
    from before the case had a ledger.
    """
    entries = read_ledger(case_dir)
    problems, notes = [], []
    prev_hash, prev_seq = GENESIS, 0
    hashes = set()
    ended = {}
    for i, e in enumerate(entries, 1):
        if "damaged" in e:
            problems.append("Line %d is not valid JSON (damaged or edited)." % i)
            continue
        seq = e.get("seq")
        if e.get("hash") != _entry_hash(e):
            problems.append("Line %d (seq %s, %s): its content does not match its hash - it "
                            "was edited." % (i, seq, e.get("event")))
        if e.get("prev") != prev_hash:
            problems.append("Line %d (seq %s): does not follow the line before it - a line was "
                            "removed, inserted or moved." % (i, seq))
        if isinstance(seq, int) and seq != prev_seq + 1:
            problems.append("Line %d: sequence jumps from %s to %s." % (i, prev_seq, seq))
        prev_hash = e.get("hash")
        prev_seq = seq if isinstance(seq, int) else prev_seq + 1
        hashes.add(e.get("hash"))
        if e.get("event") == "run ended":
            f = e.get("fields") or {}
            if f.get("record"):
                ended[f["record"]] = f.get("record_sha256")
    logs = os.path.join(os.path.abspath(case_dir), "logs")
    first_utc = next((e.get("utc") for e in entries if "utc" in e), None)
    records = sorted(n for n in (os.listdir(logs) if os.path.isdir(logs) else [])
                     if n.startswith("custody_") and n.endswith(".json"))
    for name in records:
        path = os.path.join(logs, name)
        digest, _ = sha256_file(path)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        if name in ended:
            if ended[name] and digest != ended[name]:
                problems.append("%s differs from the SHA-256 the ledger recorded when the run "
                                "ended - the record was rewritten." % name)
        elif first_utc and (data.get("started_utc") or "") >= first_utc:
            problems.append("%s is not in the ledger." % name)
        else:
            notes.append("%s predates the ledger." % name)
        anchor = data.get("ledger_entry")
        if anchor and anchor not in hashes:
            problems.append("%s points at a ledger line that is no longer there - the ledger "
                            "was cut short or replaced." % name)
    for name in ended:
        if name not in records:
            problems.append("The ledger records %s, but the file is gone." % name)
    return {"ok": not problems, "entries": len(entries), "problems": problems,
            "notes": notes, "head": prev_hash if entries else None}


def settings_changes(before, after):
    """{key: [old, new]} between two settings dicts, secrets left out."""
    before, after = before or {}, after or {}
    out = {}
    for key in sorted(set(before) | set(after)):
        if any(w in str(key).lower() for w in _SECRET_WORDS):
            continue
        if before.get(key) != after.get(key):
            out[key] = [_clean(before.get(key)), _clean(after.get(key))]
    return out


def record_export(path, what, case_dir=None, **fields):
    """A file Crow-Eye wrote for someone to read (CSV, report, JSON): its
    hash, size and what it is, in the case's ledger."""
    t = file_times(path)
    digest, _info = sha256_file(path)
    return ledger(case_dir, "export written", what=what, path=os.path.abspath(path),
                  size=t.get("size"), sha256=digest, **fields)


def _watch_export(path, what, case_dir, chosen_at, timeout=900.0):
    """Wait (on a thread of its own) until ``path`` has been written and has
    stopped changing, then record it. A file never written - the export was
    cancelled after the dialog - leaves no line."""
    def run():
        last, stable = None, 0
        while time.time() - chosen_at < timeout:
            time.sleep(1.0)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_mtime < chosen_at - 2:
                continue                      # the old file, not rewritten yet
            key = (st.st_size, st.st_mtime)
            stable = stable + 1 if key == last else 0
            last = key
            if stable >= 2:
                record_export(path, what, case_dir=case_dir)
                return
    threading.Thread(target=run, name="custody-export", daemon=True).start()


def install_export_hook():
    """Record every file saved through a Save dialog while a case is open.

    About twenty places export something (table CSVs, the database search,
    correlation results, Eye reports, the custody CSV itself). One hook on
    QFileDialog.getSaveFileName covers all of them, and any added later, the
    way the Popen hook covers processes. Needs PyQt5; idempotent.
    """
    from PyQt5 import QtWidgets
    dialog = QtWidgets.QFileDialog
    if getattr(dialog, "_crow_eye_custody", False):
        return
    original = dialog.getSaveFileName

    def getSaveFileName(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            path = result[0] if isinstance(result, tuple) else result
            if path and _CASE_DIR:
                caption = kwargs.get("caption")
                if caption is None and len(args) > 1 and isinstance(args[1], str):
                    caption = args[1]
                _watch_export(os.path.abspath(path), caption or "export", _CASE_DIR, time.time())
        except Exception:
            pass
        return result

    dialog.getSaveFileName = staticmethod(getSaveFileName)
    dialog._crow_eye_custody = True


class database_change:
    """``with database_change(db, "correlation"):`` - the database's SHA-256
    before and after a step that rewrites it, in the ledger (with how long
    the step took). For files larger than ``hash_limit`` only size and
    modified time are compared."""

    def __init__(self, db_path, what, case_dir=None, hash_limit=4 * 1024 ** 3, **fields):
        self.db_path, self.what, self.case_dir = db_path, what, case_dir
        self.hash_limit, self.fields = hash_limit, fields

    def _state(self):
        if not self.db_path or not os.path.exists(self.db_path):
            return {"exists": False}
        t = file_times(self.db_path)
        state = {"exists": True, "size": t.get("size"), "modified_utc": t.get("modified_utc")}
        if (t.get("size") or 0) <= self.hash_limit:
            state["sha256"] = sha256_file(self.db_path)[0]
        return state

    def __enter__(self):
        self.t0 = time.monotonic()
        try:
            self.before = self._state()
        except Exception:
            self.before = {}
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            after = self._state()
        except Exception:
            after = {}
        ledger(self.case_dir, "database changed", what=self.what,
               path=os.path.abspath(self.db_path) if self.db_path else None,
               before=self.before, after=after, changed=self.before != after,
               seconds=round(time.monotonic() - self.t0, 1),
               outcome="failed: %s" % exc_type.__name__ if exc_type else "completed",
               **self.fields)
        return False


# --- the open records ------------------------------------------------------------
def begin(case_dir, kind, options=None, output_dir=None, run_id=None, journal=False):
    """Open a record and make it the one this thread's code reports into.

    ``journal``: also write every entry to logs/custody_parts/<run>/ as it is
    made - needed when other processes contribute (a live parse's pool
    workers), and so the record can be salvaged if the run is killed.
    """
    global _ACTIVE
    install_process_hook()
    rec = CustodyRecord(case_dir, kind, options=options, output_dir=output_dir,
                        run_id=run_id, journal=journal)
    entry = ledger(rec.case_dir, "run started", run_id=rec.run_id, kind=kind,
                   options=rec.data.get("options"), output_dir=rec.data.get("output_dir"))
    if entry:
        rec.data["ledger_entry"] = entry["hash"]
    with _LOCK:
        first = not _OPEN
        _OPEN[rec.run_id] = rec
        _ACTIVE = rec
    if first:
        _redirect_temp(rec)
    else:
        import tempfile
        rec.data["temp_dir"] = tempfile.gettempdir()
    _THREAD.rec = rec
    return rec


def begin_fragment(case_dir, run_id, role="worker"):
    """In a worker process: report into the run ``run_id`` through a journal."""
    global _ACTIVE
    install_process_hook()
    frag = CustodyFragment(case_dir, run_id, role=role)
    with _LOCK:
        first = not _OPEN
        _OPEN[run_id] = frag
        _ACTIVE = frag
    if first:
        _redirect_temp(frag)
    _THREAD.rec = frag
    return frag


def use(rec):
    """Make ``rec`` the run this thread reports into (a worker thread a run
    started). Returns the previous one."""
    prev = getattr(_THREAD, "rec", None)
    _THREAD.rec = rec
    return prev


_SAVED_TEMPDIR = None


def _redirect_temp(rec):
    """Temporary work goes under the case, not %TEMP% on the target's system drive.

    Hive copies, transaction-log replays, the SRUM working copy, browser
    databases: every parser takes its scratch space from tempfile, whose
    default is the examined machine's own %TEMP% - writes that land in the
    unallocated space an examiner may need. Pointing tempfile at <case>/tmp
    for the length of the run moves all of them at once.
    """
    global _SAVED_TEMPDIR
    import tempfile
    target = os.path.join(rec.case_dir, "tmp")
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as e:
        rec.warn("Temporary files could not be moved under the case (%s); they go to %s."
                 % (e, tempfile.gettempdir()))
        return
    _SAVED_TEMPDIR = (tempfile.tempdir, os.environ.get("TMP"), os.environ.get("TEMP"))
    tempfile.tempdir = target
    # And for the processes started during the run (pool workers, esentutl):
    # they inherit the environment, not this module's tempfile setting.
    os.environ["TMP"] = os.environ["TEMP"] = target
    rec.data["temp_dir"] = target


def _restore_temp():
    global _SAVED_TEMPDIR
    import tempfile
    if isinstance(_SAVED_TEMPDIR, tuple):
        tdir, tmp, temp = _SAVED_TEMPDIR
        for name, value in (("TMP", tmp), ("TEMP", temp)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _SAVED_TEMPDIR = tdir
    tempfile.tempdir = _SAVED_TEMPDIR
    _SAVED_TEMPDIR = None


def active():
    """The run this thread reports into: the one it opened (or was given with
    use()), else - for helper threads - the only run open, else the newest."""
    rec = getattr(_THREAD, "rec", None)
    if rec is not None and rec.run_id in _OPEN:
        return rec
    with _LOCK:
        if len(_OPEN) == 1:
            return next(iter(_OPEN.values()))
        return _ACTIVE if (_ACTIVE is not None and _ACTIVE.run_id in _OPEN) else None


def open_runs():
    with _LOCK:
        return list(_OPEN.values())


def end(status="completed", rec=None):
    """Close this thread's record (or ``rec``); returns its path, or None.

    Two runs open at once each close their own: the second end() no longer
    finds the first run's record (or nothing) in a single global slot.
    """
    global _ACTIVE
    with _LOCK:
        if rec is None:
            rec = getattr(_THREAD, "rec", None)
            if rec is None or rec.run_id not in _OPEN:
                rec = _ACTIVE if (_ACTIVE is not None and _ACTIVE.run_id in _OPEN) else None
        if rec is None:
            return None
        _OPEN.pop(rec.run_id, None)
        if _ACTIVE is rec:
            _ACTIVE = next(reversed(list(_OPEN.values())), None) if _OPEN else None
        last = not _OPEN
    if getattr(_THREAD, "rec", None) is rec:
        _THREAD.rec = None
    if last:
        _restore_temp()
    return rec.close(status)


def footprint(kind, detail, **extra):
    rec = active()
    return rec.footprint(kind, detail, **extra) if rec else None


def _command_text(command):
    if isinstance(command, (list, tuple)):
        return " ".join(str(c) for c in command)
    return str(command)


def note_process(command, purpose=None, returncode=None):
    """Say why a process ran, and how it ended.

    The Popen hook has usually recorded the process already, when it started;
    this adds the purpose and return code to that entry instead of writing a
    second one. Without the hook it writes the entry itself.
    """
    rec = active()
    if rec is None:
        return None
    text = _command_text(command)
    with rec._lock:
        for item in reversed(rec.data["footprint"]):
            if item.get("kind") == "process" and item.get("detail") == text and "purpose" not in item:
                if purpose:
                    item["purpose"] = purpose
                if returncode is not None:
                    item["returncode"] = returncode
                rec.note_purpose(text, purpose, returncode)
                return item
    return rec.footprint("process", text, purpose=purpose, returncode=returncode)


_HOOKED = False


def install_process_hook():
    """Record every process Crow-Eye starts while a record is open.

    One hook on subprocess.Popen instead of a call beside each of the ~40
    subprocess.run sites in the VSS diagnostics, the parsers and the
    collectors: a site added later is recorded too, which a per-call note would
    silently miss. A process that fails to start is a failure entry. Also
    hooked: os.startfile (opening a file or folder with its default program)
    and ShellExecuteW, which utils/elevation.py uses to relaunch elevated.
    Outside a collection the hooks do nothing.
    """
    global _HOOKED
    with _LOCK:
        if _HOOKED:
            return
        import subprocess
        original = subprocess.Popen.__init__

        def __init__(self, args, *a, **kw):
            try:
                original(self, args, *a, **kw)
            except Exception as e:
                rec = active()
                if rec is not None:
                    try:
                        rec.add_failure(_command_text(args), "process did not start: %s: %s"
                                        % (type(e).__name__, e), method="process")
                    except Exception:
                        pass
                raise
            rec = active()
            if rec is not None:
                try:
                    rec.footprint("process", _command_text(args), pid=getattr(self, "pid", None))
                except Exception:
                    pass

        subprocess.Popen.__init__ = __init__

        start = getattr(os, "startfile", None)
        if start is not None:
            def startfile(path, *a, **kw):
                rec = active()
                if rec is not None:
                    try:
                        rec.footprint("process", "open with the default program: %s" % path)
                    except Exception:
                        pass
                return start(path, *a, **kw)
            os.startfile = startfile

        if os.name == "nt":
            try:
                import ctypes
                shell32 = ctypes.windll.shell32
                real = shell32.ShellExecuteW

                class _ShellExecute:
                    """Wraps the ctypes function object, which cannot take a
                    Python attribute in its place on every version."""
                    def __getattr__(self, name):
                        return getattr(real, name)

                    def __setattr__(self, name, value):
                        setattr(real, name, value)

                    def __call__(self, hwnd, verb, file, params, *rest):
                        rec = active()
                        if rec is not None:
                            try:
                                rec.footprint("process", "ShellExecute %s %s %s"
                                              % (verb or "", file or "", params or ""))
                            except Exception:
                                pass
                        return real(hwnd, verb, file, params, *rest)

                shell32.ShellExecuteW = _ShellExecute()
            except Exception:
                pass
        _HOOKED = True


def note_shadow_copy(action, **kw):
    rec = active()
    if rec:
        rec.shadow_copy(action, **kw)


def warn(message):
    rec = active()
    if rec:
        rec.warn(message)
