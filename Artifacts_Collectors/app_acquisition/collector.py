"""The copy: every selected footprint item into the case, with custody.

Layout, one folder per acquisition so a second one never mixes with the first:

    <case>/app_acquisition/<program>_<UTC stamp>/
        <live | image tag>/<path below the volume>   the files, path kept
        registry/<hive>__<key>.json                  exported keys
        app_manifest.json                            file -> why, user, hash

It is outside live_acquisition/ on purpose: the Offline Importer scans that
folder with no exclusions and would try to parse every file of the program.

Each file is recorded in a chain-of-custody record (kind "application
acquisition"): its times before the copy, how it was read (copy, shadow copy,
raw clusters, image), and SHA-256 of the source and the copy. Shadow copies
this run created are deleted before the record closes.

Every SQLite database among the copies also gets a working copy under
Target_Artifacts/Imported_Evidence/<program>/ (with its -wal / -shm), recorded
in the imported-evidence manifest, so Database Search and Eye can read the
program's saved data at once. The copy under app_acquisition/ stays untouched.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .footprint import Footprint, FootprintItem
from .registry import SOFTWARE, RegistryView

logger = logging.getLogger(__name__)

ACQUISITION_DIR = "app_acquisition"
_SQLITE_MAGIC = b"SQLite format 3\x00"
_SIDECARS = ("-wal", "-shm", "-journal")
_MAX_LISTED_ERRORS = 50


def _utc_now():
    return datetime.now(timezone.utc)


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", text or "program").strip("._")
    return (s or "program")[:60]


@dataclass
class AcquisitionResult:
    folder: str = ""
    files: int = 0
    bytes: int = 0
    failed: int = 0
    registry_keys: int = 0
    databases: List[str] = field(default_factory=list)      # working copies for Database Search
    errors: List[str] = field(default_factory=list)
    custody_path: Optional[str] = None
    cancelled: bool = False
    disk_full: bool = False

    @property
    def status(self) -> str:
        if self.cancelled:
            return "cancelled"
        if self.files == 0 and self.registry_keys == 0:
            return "failed"
        return "partial" if (self.failed or self.disk_full) else "completed"


def acquire(footprint: Footprint, source, case_root: str,
            progress: Optional[Callable[[str, int, int], None]] = None,
            is_cancelled: Optional[Callable[[], bool]] = None,
            view: Optional[RegistryView] = None,
            record_kind: str = "application acquisition") -> AcquisitionResult:
    """Copy the selected items of ``footprint`` from ``source`` into the case.
    ``record_kind`` names the chain-of-custody record: "application
    acquisition" for a program, "file collection" for files the File Browser
    or the Shadow Copies window picked."""
    say = progress or (lambda _m, _d, _t: None)
    stop = is_cancelled or (lambda: False)
    app = footprint.app
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    folder = os.path.join(case_root, ACQUISITION_DIR, "%s_%s" % (_slug(app.name), stamp))
    files_root = os.path.join(folder, source.tag)
    os.makedirs(files_root, exist_ok=True)
    result = AcquisitionResult(folder=folder)
    selected = [i for i in footprint.items if i.selected]
    logger.info("%s: %s - %d item(s) from %s into %s", record_kind.capitalize(), app.label(),
                len(selected), source.describe(), folder)

    try:
        from utils import custody
    except Exception:
        custody = None
    rec = None
    if custody is not None:
        try:
            rec = custody.begin(case_root, record_kind, options={
                "application": app.label(), "install_dir": app.install_dir,
                "source": source.describe(), "source_kind": source.kind,
                "items": [{"kind": i.kind, "path": i.path, "hive": i.hive or None,
                           "reason": i.reason, "user": i.user or None} for i in selected],
            }, output_dir=folder)
        except Exception as exc:
            logger.warning("Chain-of-custody record not started: %s", exc)

    manifest_files = []
    copied = set()
    started = _utc_now()
    try:
        # Files first, counted up front so the progress bar means something.
        plan = []
        for item in selected:
            if item.kind == "registry":
                continue
            for rel, size in source.walk_files(item.path):
                key = rel.lower()
                if key in copied:
                    continue
                copied.add(key)
                plan.append((item, rel, size))
                if stop():
                    break
        total = len(plan)
        for n, (item, rel, size) in enumerate(plan, 1):
            if stop():
                result.cancelled = True
                break
            if n == 1 or n % 25 == 0 or n == total:
                say("Copying %s" % rel, n, total)
            dest = os.path.join(files_root, rel)
            try:
                ok, method, detail = source.copy_file(rel, dest)
            except OSError as exc:
                ok, method, detail = False, None, {"error": str(exc), "source": rel}
                if getattr(exc, "winerror", None) == 112 or getattr(exc, "errno", None) == 28:
                    result.disk_full = True
            if result.disk_full or "not enough space" in str(detail.get("error", "")).lower():
                result.disk_full = True
                result.errors.append("The case drive is full: the acquisition stopped at %s" % rel)
                break
            if not ok:
                result.failed += 1
                logger.warning("Not copied: %s (%s)", rel, detail.get("error") or "copy failed")
                if rec is not None:
                    rec.add_failure(detail.get("source") or rel, detail.get("error") or "copy failed", method)
                if len(result.errors) < _MAX_LISTED_ERRORS:
                    result.errors.append("%s: %s" % (rel, detail.get("error") or "copy failed"))
                continue
            entry = _record(rec, source, dest, method, detail)
            result.files += 1
            try:
                result.bytes += os.path.getsize(dest)
            except OSError:
                pass
            manifest_files.append({
                "path": rel, "copy": os.path.relpath(dest, folder), "size": entry.get("copy_size"),
                "sha256": entry.get("copy_sha256"), "source_sha256": entry.get("source_sha256"),
                "verified": entry.get("verified"), "method": method,
                "reason": item.reason, "user": item.user or None,
            })
        if result.failed > len(result.errors):
            result.errors.append("... and %d more file(s) could not be copied"
                                 % (result.failed - len(result.errors)))

        # Registry keys.
        if not result.cancelled and not result.disk_full:
            view = view or RegistryView(source)
            reg_dir = os.path.join(folder, "registry")
            for item in (i for i in selected if i.kind == "registry"):
                if stop():
                    result.cancelled = True
                    break
                say("Exporting %s" % item.path, 0, 0)
                try:
                    data = view.export(item.hive or SOFTWARE, item.path)
                except Exception as exc:
                    result.errors.append("Registry %s: %s" % (item.path, exc))
                    continue
                data.update(reason=item.reason, user=item.user or None, source=source.describe(),
                            exported_utc=_utc_now().isoformat())
                os.makedirs(reg_dir, exist_ok=True)
                name = "%s__%s.json" % (_slug((item.hive or SOFTWARE).replace(":", "_")), _slug(item.path))
                path = os.path.join(reg_dir, name)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=1, ensure_ascii=False, default=str)
                result.registry_keys += 1
                if rec is not None:
                    try:
                        rec.add_output(path, kind="registry export",
                                       note="%s\\%s" % (data.get("hive"), item.path))
                    except Exception:
                        pass

        # Searchable working copies of the program's databases.
        if not result.cancelled:
            say("Preparing the program's databases for Database Search", 0, 0)
            result.databases = _working_copies(folder, files_root, case_root, app.label(), manifest_files)
    finally:
        if source.kind == "live":
            try:
                from Artifacts_Collectors.crow_claw.core.shadow_copy_manager import delete_created_shadow_copies
                for sid, gone in delete_created_shadow_copies().items():
                    if not gone:
                        result.errors.append("A shadow copy this acquisition created could not be "
                                             "deleted: %s" % sid)
            except Exception as exc:
                logger.warning("Shadow copy cleanup failed: %s", exc)
        if rec is not None:
            try:
                rec.data["acquisition"] = {"files": result.files, "bytes": result.bytes,
                                           "failed": result.failed, "registry_keys": result.registry_keys,
                                           "databases": len(result.databases)}
                result.custody_path = custody.end(result.status, rec)
            except Exception as exc:
                logger.error("Chain-of-custody record not written: %s", exc)
        # After the record closes, so the manifest can name it.
        _write_manifest(folder, footprint, source, selected, manifest_files, result, started)
        logger.info("%s %s: %d file(s), %d byte(s), %d not copied, %d registry key(s); custody %s",
                    record_kind.capitalize(), result.status, result.files, result.bytes,
                    result.failed, result.registry_keys, result.custody_path)
    return result


def _record(rec, source, dest, method, detail) -> dict:
    """The custody entry for one copy (hashes of both sides where possible)."""
    if rec is None:
        from utils.custody import sha256_file
        digest, info = sha256_file(dest)
        return {"copy_sha256": digest, "copy_size": info if digest else None, "verified": None}
    try:
        if source.kind == "image":
            # The source is inside the image: the copy is its only readable form.
            return rec.add_source(detail["source"], copy=dest, method="image", times=detail.get("times") or {},
                                  hash_source=False, note="read from the forensic image")
        if source.kind in ("image_shadow", "hidden_shadow"):
            # A shadow copy rebuilt by Crow-Eye's VSS reader has no path to hash
            # again: the bytes read are the copy, recorded with the copy that
            # held them (before, the pseudo-path was hashed and every entry
            # carried a source_hash_error).
            return rec.add_source(detail["source"], copy=dest, method=method or "shadow_copy",
                                  times=detail.get("times") or {}, hash_source=False,
                                  shadow_copy_id=detail.get("shadow_copy_id"),
                                  shadow_copy_created_utc=detail.get("shadow_copy_created_utc"),
                                  note="read from a shadow copy rebuilt by Crow-Eye's VSS reader; "
                                       "the copy is its only readable form")
        return rec.add_source(detail["source"], copy=dest, method=method or "standard",
                              times=detail.get("times"), read_from=detail.get("read_from"),
                              shadow_copy_id=detail.get("shadow_copy_id"),
                              shadow_copy_created_utc=detail.get("shadow_copy_created_utc"))
    except Exception as exc:
        logger.warning("Custody entry for %s not recorded: %s", dest, exc)
        return {}


def _is_sqlite(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == _SQLITE_MAGIC
    except OSError:
        return False


def _working_copies(folder, files_root, case_root, label, manifest_files) -> List[str]:
    """Working copies of every SQLite database, registered as imported evidence."""
    artifacts_dir = os.path.join(case_root, "Target_Artifacts")
    if not os.path.isdir(artifacts_dir):
        return []
    try:
        from eye.services.imported_evidence_manifest import manifest_for_case, IMPORTED_SUBDIR
    except Exception as exc:
        logger.info("Imported-evidence manifest unavailable: %s", exc)
        return []
    manifest = manifest_for_case(artifacts_dir)
    dest_dir = os.path.join(artifacts_dir, IMPORTED_SUBDIR, "App_" + os.path.basename(folder))
    out = []
    for f in manifest_files:
        evidence = os.path.join(folder, f["copy"])
        if f["copy"].lower().endswith(_SIDECARS) or not _is_sqlite(evidence):
            continue
        # One readable name per database: the folders it sat in say whose it is.
        rel = f["path"]
        parts = rel.split("\\")
        short = "_".join(parts[-3:]) if len(parts) >= 3 else "_".join(parts)
        name = _slug(short)
        if not name.lower().endswith(".db"):
            name += ".db"
        dest = os.path.join(dest_dir, name)
        i = 2
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, "%s_%d.db" % (name[:-3], i))
            i += 1
        try:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(evidence, dest)
            for side in _SIDECARS:
                if os.path.exists(evidence + side):
                    shutil.copy2(evidence + side, dest + side)
        except OSError as exc:
            logger.warning("Working copy of %s not made: %s", evidence, exc)
            continue
        f["working_copy"] = os.path.relpath(dest, case_root)
        out.append(dest)
        if manifest is not None:
            manifest.record_import(evidence, dest, "database",
                                   extra={"origin": "application acquisition", "application": label,
                                          "original_path": rel, "user": f.get("user")})
    return out


def _write_manifest(folder, footprint, source, selected, files, result, started):
    app = footprint.app
    data = {
        "format": "crow-eye application acquisition 1",
        "application": {"name": app.name, "publisher": app.publisher, "version": app.version,
                        "install_dir": app.install_dir, "executables": app.exes,
                        "seen_in": app.sources, "last_run": app.last_run or None},
        "source": source.describe(),
        "source_kind": source.kind,
        "started_utc": started.isoformat(),
        "finished_utc": _utc_now().isoformat(),
        "status": result.status,
        "totals": {"files": result.files, "bytes": result.bytes, "failed": result.failed,
                   "registry_keys": result.registry_keys, "databases": len(result.databases)},
        "items": [{"kind": i.kind, "path": i.path, "hive": i.hive or None, "reason": i.reason,
                   "user": i.user or None} for i in selected],
        "not_selected": [{"kind": i.kind, "path": i.path, "reason": i.reason}
                         for i in footprint.items if not i.selected],
        "notes": footprint.notes,
        "errors": result.errors,
        "custody_record": result.custody_path,
        "files": files,
    }
    try:
        with open(os.path.join(folder, "app_manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False, default=str)
    except OSError as exc:
        logger.error("Acquisition manifest not written: %s", exc)
