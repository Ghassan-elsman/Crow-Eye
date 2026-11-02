"""Put files from a shadow copy (or any source) back on this machine.

Recovery has two destinations and the examiner may choose both: the case, as evidence (the
collector: SHA-256, custody, manifest), and this machine, as a working copy for the user. This
module is the second.

Restoring never overwrites. A file whose original place is free goes back there; one whose place
is taken goes beside it as "name (restored from <copy>).ext", so the current file and the old one
can be compared; and a chosen folder receives the paths below it unchanged. Every restored file is
hashed after it is written, and the run - what, from which copy, where, by whom - is a manifest in
the case's Restores folder and a line in the case's custody ledger, because putting a file back
on an examined machine changes that machine and must be accounted for.
"""
from __future__ import annotations

import datetime
import logging
import hashlib
import json
import os
from typing import Callable, Iterable, List, Optional, Tuple

ORIGINAL = "original"
FOLDER = "folder"

_log = logging.getLogger(__name__)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _beside(path: str, label: str) -> str:
    """'C:\\a\\b.txt' -> 'C:\\a\\b (restored from #232 2026-10-29).txt', unique."""
    stem, ext = os.path.splitext(path)
    cand = "%s (restored from %s)%s" % (stem, label, ext)
    n = 2
    while os.path.exists(cand):
        cand = "%s (restored from %s, %d)%s" % (stem, label, n, ext)
        n += 1
    return cand


def plan_targets(rels: Iterable[Tuple[str, int]], volume: str, mode: str, folder: Optional[str],
                 label: str, root: Optional[str] = None) -> List[Tuple[str, str, int, str]]:
    """[(rel, target, size, how)] for the files to restore; how: 'original' / 'beside' / 'folder'.
    ``root`` stands in for the volume's root (tests)."""
    out = []
    for rel, size in rels:
        if mode == FOLDER:
            out.append((rel, os.path.join(folder, rel), size, "folder"))
            continue
        target = os.path.join(root, rel) if root else "%s:\\%s" % (volume.rstrip(":\\"), rel)
        if os.path.exists(target):
            out.append((rel, _beside(target, label), size, "beside"))
        else:
            out.append((rel, target, size, "original"))
    return out


def restore(source, picks: List[Tuple[str, bool]], case_root: Optional[str], mode: str = ORIGINAL,
            folder: Optional[str] = None, progress: Callable = None,
            is_cancelled: Callable = None) -> dict:
    """Restore the ticked files and folders. Returns {status, restored:[...], failed:[...],
    manifest, bytes}."""
    volume = (getattr(source, "copy", {}) or {}).get("volume") or "C"
    created = (getattr(source, "copy", {}) or {}).get("created", "")
    number = (getattr(source, "copy", {}) or {}).get("number")
    label = ("shadow copy #%s %s" % (number, created[:10])) if number else (
        "shadow copy %s" % created[:16].replace("T", " ") if created else source.tag)
    files = []
    for rel, is_dir in picks:
        files += list(source.walk_files(rel)) if is_dir else [(rel, source.size(rel))]
    targets = plan_targets(files, volume, mode, folder, label.replace(":", ""))
    restored, failed, total = [], [], 0
    tmp_root = None
    for i, (rel, target, size, how) in enumerate(targets):
        if is_cancelled and is_cancelled():
            break
        if progress:
            progress("Restoring %s" % rel, i, len(targets))
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            ok, method, detail = source.copy_file(rel, target)
            if not ok:
                failed.append({"path": rel, "error": detail.get("error") or "copy failed"})
                continue
            digest = _sha256(target)
            total += os.path.getsize(target)
            restored.append({"path": rel, "restored_to": target, "how": how, "sha256": digest,
                             "size": os.path.getsize(target), "method": method,
                             "source_times": detail.get("times")})
        except OSError as exc:
            failed.append({"path": rel, "error": str(exc)})
    for f in failed:
        _log.warning("Not restored: %s (%s)", f["path"], f["error"])
    status = "cancelled" if (is_cancelled and is_cancelled()) else (
        "completed" if restored and not failed else ("partial" if restored else "failed"))
    manifest = None
    if case_root:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        folder_out = os.path.join(case_root, "Restores")
        os.makedirs(folder_out, exist_ok=True)
        manifest = os.path.join(folder_out, "restore_%s.json" % stamp)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"restored_utc": stamp, "source": source.describe(), "source_tag": source.tag,
                       "shadow_copy": getattr(source, "copy", None), "mode": mode, "folder": folder,
                       "status": status, "files": restored, "failed": failed}, fh, indent=2, default=str)
        try:
            from utils import custody
            custody.record_export(manifest, "files restored to this machine from %s" % source.describe(),
                                  case_dir=case_root, files=len(restored), failed=len(failed), mode=mode)
        except Exception:
            pass
    _log.info("Restore %s from %s (%s): %d file(s) restored, %d not; manifest %s",
              status, source.describe(), mode, len(restored), len(failed), manifest)
    if progress:
        progress("Restored %d file(s)" % len(restored), len(targets), len(targets))
    return {"status": status, "restored": restored, "failed": failed, "manifest": manifest, "bytes": total}
