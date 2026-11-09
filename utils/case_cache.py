"""Answers of whole-case questions, kept beside the case until a database
changes. The timeline's opening questions (timeline/case_cache.py) and the
MFT/USN dashboard's (visualizations/mftusn_bridge.py) are kept here.

Why: a dashboard asks the whole case the same questions every time it opens,
for answers that only change when a parse writes a database - the timeline's
bounds and day counts (3.4 s and 2.0 s on a real case), the MFT/USN overview
and strip (10 s and 9 s on 3.9 M correlated rows).

Each answer is stored in a JSON file beside the case (``<case>/<folder>/
<file>``) under its question and arguments, with the size and mtime of every
database in Target_Artifacts (and of its WAL) at the time it was computed. A
stored answer is used only while every one of those still matches; a parse, a
re-parse or an import changes one, and the next opening asks again. A memory
copy saves the file read within one run.

AN EMPTY WAL IS NOT A CHANGE. A database in WAL mode keeps a zero-byte -wal
file whose mtime moves every time a connection opens it, writing nothing:
keyed on that mtime, every stored answer went stale whenever any dashboard
had read the case (prefetch_data.db-wal, 0 bytes, a new time on every read).
An empty WAL is recorded as [0, 0]; a WAL holding pages keeps its size and
mtime, since a checkpoint rewrites a WAL from its start at the same size.
"""

import json
import os
import threading

_MEM = {}
_LOCK = threading.Lock()


def path_for(artifacts_dir, folder, filename):
    base = os.path.abspath(artifacts_dir or ".")
    if os.path.basename(base.rstrip("\\/")).lower() == "target_artifacts":
        base = os.path.dirname(base.rstrip("\\/"))
    return os.path.join(base, folder, filename)


def signature(artifacts_dir):
    """{file: size} for every database the case holds.

    Size only. A re-parse is append-only (dedupe_insert), so it grows a
    database; merely opening and reading the case never changes its size. mtime
    and the -wal file are excluded on purpose - a loader opens a database
    read-write and its connection checkpoints the WAL on close, which bumps the
    .db mtime and the -wal file even on a pure read, and keying on them made
    every stored answer go stale whenever the case had been read (the Timeline
    re-ran its 3.4 s bounds + 2 s day counts, the MFT/USN dashboard re-queried).
    """
    out = {}
    try:
        names = os.listdir(artifacts_dir)
    except OSError:
        return out
    for name in sorted(names):
        low = name.lower()
        if not (low.endswith(".db") or low.endswith(".sqlite")):
            continue
        try:
            out[name] = os.stat(os.path.join(artifacts_dir, name)).st_size
        except OSError:
            continue
    # Imported evidence widens the bounds too (getImportedData).
    imported = os.path.join(artifacts_dir, "Imported_Evidence")
    if os.path.isdir(imported):
        for root, _dirs, files in os.walk(imported):
            for name in files:
                try:
                    out[os.path.relpath(os.path.join(root, name),
                                        artifacts_dir).replace("\\", "/")] = \
                        os.stat(os.path.join(root, name)).st_size
                except OSError:
                    continue
    return out


def _load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def get(artifacts_dir, key, folder, filename):
    """The stored answer for `key`, or None when absent or stale."""
    path = path_for(artifacts_dir, folder, filename)
    sig = signature(artifacts_dir)
    with _LOCK:
        body = _MEM.get(path)
        if body is None:
            body = _MEM[path] = _load(path)
    entry = body.get(key)
    if not entry or entry.get("sig") != sig:
        return None
    return entry.get("answer")


def put(artifacts_dir, key, answer, folder, filename, sig=None):
    """Store `answer` for `key`. `sig` is the signature taken BEFORE the
    answer was computed, so a database written meanwhile makes it stale.
    Entries whose signature no longer matches the case are dropped on the
    way, so the file holds the current answers and not every past one."""
    path = path_for(artifacts_dir, folder, filename)
    now = sig if sig is not None else signature(artifacts_dir)
    with _LOCK:
        body = dict(_MEM.get(path) or _load(path))
        body = {k: v for k, v in body.items()
                if isinstance(v, dict) and v.get("sig") == now}
        body[key] = {"sig": now, "answer": answer}
        _MEM[path] = body
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(body, handle)
            os.replace(tmp, path)
        except OSError:
            pass  # the memory copy still serves this run
