"""
Imported Evidence Manifest — chain-of-custody ledger for external evidence.

Every file an investigator imports into a case (converted SQLite databases AND
verbatim documents such as third-party reports, email exports, browser-forensics
output) gets a manifest entry with SHA-256 hashes of BOTH the original source
file and the copy that landed inside the case. The manifest backs:

- the Imported Evidence window (list + live integrity verification),
- the Compliance window's activity stream (IMPORT entries with hashes),
- the ``read_imported_evidence`` tool (document discovery).

The manifest lives next to the evidence it describes:
``<case>/Target_Artifacts/Imported_Evidence/imported_evidence_manifest.json``

Hashing streams in 1 MB chunks so multi-GB databases never load into memory.
Callers are expected to invoke hashing methods OFF the GUI thread (import
workers / bridge QThreads already do).
"""

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

IMPORTED_SUBDIR = "Imported_Evidence"
DOCUMENTS_SUBDIR = "Documents"
MANIFEST_NAME = "imported_evidence_manifest.json"

# Extensions imported VERBATIM as documents (no conversion): third-party
# reports, Gmail/e-mail exports, browser-forensics tool output, plain logs.
DOCUMENT_EXTENSIONS = {".pdf", ".html", ".htm", ".txt", ".md", ".log", ".eml", ".mbox"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """Streamed SHA-256 of a file; None when unreadable/missing."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.warning(f"Could not hash {path}: {e}")
        return None


class ImportedEvidenceManifest:
    """Per-case ledger of imported evidence with source/dest SHA-256 hashes."""

    def __init__(self, artifacts_dir):
        """``artifacts_dir`` is the case's Target_Artifacts directory (the same
        root FeatherImporter uses)."""
        self.artifacts_dir = Path(artifacts_dir)
        self.imported_dir = self.artifacts_dir / IMPORTED_SUBDIR
        self.documents_dir = self.imported_dir / DOCUMENTS_SUBDIR
        self.manifest_path = self.imported_dir / MANIFEST_NAME
        self._lock = threading.Lock()

    # ── persistence ────────────────────────────────────────────────

    def _load(self) -> List[Dict[str, Any]]:
        try:
            if self.manifest_path.exists():
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data = data.get("entries") or []
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"Could not read imported-evidence manifest: {e}")
        return []

    def _save(self, entries: List[Dict[str, Any]]) -> None:
        try:
            self.imported_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.manifest_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": 1, "entries": entries},
                                      indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.manifest_path)
        except Exception as e:
            logger.error(f"Could not write imported-evidence manifest: {e}")

    # ── recording ──────────────────────────────────────────────────

    def record_import(self, src_path, dest_path, kind: str,
                      extra: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Append a ledger entry for a completed import. ``kind`` is
        ``"database"`` (converted/copied SQLite) or ``"document"`` (verbatim
        report/e-mail/browser output). Hashes BOTH files (streamed). Returns the
        entry, or None on failure. Call off the GUI thread."""
        try:
            src = Path(src_path)
            dest = Path(dest_path)
            entry: Dict[str, Any] = {
                "id": f"imp_{int(datetime.now().timestamp() * 1000)}",
                "name": dest.name,
                "kind": kind,
                "imported_at": _utc_now(),
                "source_path": str(src),
                "dest_path": str(dest),
                "size_bytes": dest.stat().st_size if dest.exists() else None,
                "sha256_source": sha256_file(src),
                "sha256": sha256_file(dest),
            }
            for k, v in (extra or {}).items():
                if v is not None:
                    entry[k] = v
            with self._lock:
                entries = self._load()
                entries.append(entry)
                self._save(entries)
            logger.info(f"Imported-evidence manifest: recorded {entry['name']} "
                        f"({kind}, sha256={str(entry['sha256'])[:12]}…)")
            return entry
        except Exception as e:
            logger.error(f"record_import failed: {e}", exc_info=True)
            return None

    def backfill(self) -> int:
        """Add late entries (``hashed_late: true``) for evidence files already in
        ``Imported_Evidence/`` that pre-date the manifest. Returns count added."""
        added = 0
        try:
            if not self.imported_dir.exists():
                return 0
            with self._lock:
                entries = self._load()
                known = {e.get("dest_path") for e in entries}
                candidates: List[Path] = []
                for p in self.imported_dir.glob("*"):
                    if p.is_file() and p.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
                        candidates.append(p)
                if self.documents_dir.exists():
                    for p in self.documents_dir.glob("*"):
                        if p.is_file():
                            candidates.append(p)
                for p in candidates:
                    if str(p) in known or p.name == MANIFEST_NAME:
                        continue
                    entries.append({
                        "id": f"imp_bf_{int(datetime.now().timestamp() * 1000)}_{added}",
                        "name": p.name,
                        "kind": "document" if self.documents_dir in p.parents else "database",
                        "imported_at": _utc_now(),
                        "source_path": None,
                        "dest_path": str(p),
                        "size_bytes": p.stat().st_size,
                        "sha256_source": None,
                        "sha256": sha256_file(p),
                        "hashed_late": True,
                    })
                    added += 1
                if added:
                    self._save(entries)
        except Exception as e:
            logger.error(f"backfill failed: {e}", exc_info=True)
        if added:
            logger.info(f"Imported-evidence manifest: backfilled {added} pre-existing file(s)")
        return added

    # ── listing / verification ─────────────────────────────────────

    def list_entries(self, verify: bool = False) -> List[Dict[str, Any]]:
        """All ledger entries, newest first. With ``verify=True`` each entry is
        re-hashed and gains ``integrity``: ``verified`` / ``mismatch`` /
        ``missing`` (re-hashing streams the file — call off the GUI thread)."""
        self.backfill()
        entries = list(reversed(self._load()))
        if verify:
            for e in entries:
                dest = e.get("dest_path")
                if not dest or not Path(dest).exists():
                    e["integrity"] = "missing"
                    continue
                current = sha256_file(dest)
                recorded = e.get("sha256")
                e["integrity"] = ("verified" if current and recorded and current == recorded
                                  else "mismatch")
        return entries

    def list_documents(self) -> List[Dict[str, Any]]:
        """Manifest entries of kind=document (for the read_imported_evidence tool)."""
        return [e for e in self.list_entries() if e.get("kind") == "document"]


def manifest_for_case(artifacts_dir) -> Optional[ImportedEvidenceManifest]:
    """Convenience constructor; None when no artifacts dir is known."""
    if not artifacts_dir:
        return None
    try:
        return ImportedEvidenceManifest(artifacts_dir)
    except Exception as e:
        logger.error(f"Could not create ImportedEvidenceManifest: {e}")
        return None
