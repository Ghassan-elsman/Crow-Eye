"""
EvidenceSeal — auditable, tamper-evident chain of custody for what the AI actually saw.

Every payload the Eye sends to an LLM is sealed here: the SHA-256 of the EXACT
bytes injected into the prompt, the token count, the model + its context limit,
and the provenance of the evidence rows that were fed in (database:table:rowid,
source path / record number / computed file offset where available).

Records are written append-only as JSON-lines to
``<case>/EYE_Logs/eye_payload_seal.jsonl`` and are **hash-chained** (each
record's seal_hash folds in the previous one) so a single altered or removed
record breaks the chain — the same non-repudiation property used for report
blocks. If opposing counsel questions an answer, this log proves mathematically
which exact bytes the model analyzed.
"""

import os
import gzip
import json
import hashlib
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

try:
    import zstandard as _zstd  # preferred: smaller, faster
except Exception:  # pragma: no cover - optional dependency
    _zstd = None


def _compress_file_to_variant(txt_path: Path) -> Optional[Path]:
    """Compress ``<name>.txt`` to ``<name>.txt.zst`` (or ``.gz`` fallback) and
    remove the original. Best-effort: returns the new path or None on failure /
    if the source is missing. Used to shrink older sealed-payload sidecars."""
    try:
        if not txt_path.exists():
            return None
        data = txt_path.read_bytes()
        if _zstd is not None:
            blob = _zstd.ZstdCompressor(level=10).compress(data)
            out = Path(str(txt_path) + ".zst")
        else:
            blob = gzip.compress(data)
            out = Path(str(txt_path) + ".gz")
        with open(out, "wb") as f:
            f.write(blob)
        txt_path.unlink()
        return out
    except Exception:
        return None


def read_payload_sidecar(payload_dir: Path, sha: str) -> Optional[str]:
    """Resolve and return the plaintext of a sealed-payload sidecar, transparently
    decompressing ``.txt.zst`` / ``.txt.gz`` variants. Returns None if absent (or
    if it is zstd-compressed but the ``zstandard`` library is unavailable).

    The returned plaintext re-hashes to the seal's ``payload_sha256`` regardless
    of on-disk compression — verification works the same."""
    base = payload_dir / f"{sha}.txt"
    try:
        if base.exists():
            return base.read_text(encoding="utf-8")
        zst = Path(str(base) + ".zst")
        if zst.exists():
            if _zstd is None:
                return None
            return _zstd.ZstdDecompressor().decompress(zst.read_bytes()).decode("utf-8", errors="replace")
        gz = Path(str(base) + ".gz")
        if gz.exists():
            return gzip.decompress(gz.read_bytes()).decode("utf-8", errors="replace")
    except Exception:
        return None
    return None


class EvidenceSeal:
    """Writes and chains per-payload evidence seals for chain of custody."""

    # Max characters of dropped/processed content kept INLINE in the seal +
    # audit log. Anything longer is previewed inline (head) and the COMPLETE
    # bytes are spilled to a per-hash sidecar under EYE_Logs/dropped_payloads/
    # so the logs stay readable while every byte remains recoverable for court.
    CUT_PREVIEW_CHARS = 4000

    # Max characters scanned for forensic-artifact offsets. For content larger
    # than this, only the head + tail slices are swept (the boundaries where
    # markers cluster); the full bytes still live in the sidecar for manual
    # review. Bounds the regex cost in the request path on multi-MB drops.
    OFFSET_SCAN_MAX_CHARS = 200_000

    # Assumed NTFS MFT record size used to map a record number to a byte offset.
    # Standard volumes use 1024 B; some (esp. large-cluster) volumes use 4096 B.
    # The assumed size is emitted as ``record_size`` so a verifier can re-derive.
    MFT_RECORD_SIZE = 1024

    def __init__(self, case_directory: Union[str, Path], store_full_payload: bool = True):
        self.case_directory = Path(case_directory) if case_directory else None
        self.logger = logging.getLogger(self.__class__.__name__)
        self._seq = 0
        self._prev_seal_hash = ""
        self._lock = threading.Lock()  # guards _seq/_prev_seal_hash + append
        self._log_path: Optional[Path] = None
        self._spill_dir: Optional[Path] = None
        # Full-sent-payload persistence (independently reproducible seals). The
        # most recent N payloads stay uncompressed; older ones are compressed.
        self.store_full_payload = store_full_payload
        self._payload_dir: Optional[Path] = None
        self._recent_uncompressed = 10
        self._recent_payload_shas: List[str] = []
        if self.case_directory:
            self._log_path = self.case_directory / "EYE_Logs" / "eye_payload_seal.jsonl"
            self._spill_dir = self.case_directory / "EYE_Logs" / "dropped_payloads"
            self._payload_dir = self.case_directory / "EYE_Logs" / "sealed_payloads"
            self._recover_chain()
            self._seed_recent_payloads()

    def _recover_chain(self) -> None:
        """Resume the hash chain + sequence from an existing log (tamper-evident
        continuity across sessions)."""
        try:
            if self._log_path and self._log_path.exists():
                last = None
                with open(self._log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            last = line
                if last:
                    rec = json.loads(last)
                    self._seq = int(rec.get("seq", 0))
                    self._prev_seal_hash = rec.get("seal_hash", "") or ""
        except Exception as e:
            self.logger.warning(f"Could not recover seal chain: {e}")

    @staticmethod
    def _sha256(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()

    def verify_chain(self) -> bool:
        """Re-walk the persisted payload seal log and confirm the tamper-evident
        hash chain is intact end-to-end: for every record,
        ``seal_hash == sha256(prev_seal_hash + payload_sha256 + metadata_sha256)``
        and ``prev_seal_hash`` links to the previous record's ``seal_hash``.

        Returns ``True`` when the chain verifies (an empty/missing log is
        vacuously valid — nothing has been sealed to break). Best-effort: an I/O
        or parse error returns ``False`` (an unreadable integrity log is not a
        pass). This is the single source of truth reused by the bridge
        (``get_payload_seals``) and the compliance dashboard.
        """
        try:
            if not self._log_path or not self._log_path.exists():
                return True
            prev = ""
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        s = json.loads(line)
                    except Exception:
                        return False
                    p_hash = s.get("payload_sha256", "")
                    m_hash = s.get("metadata_sha256", "")
                    if m_hash:
                        expected = self._sha256(prev + p_hash + m_hash)
                    else:
                        expected = self._sha256(prev + p_hash)  # legacy format
                    if s.get("prev_seal_hash", "") != prev or s.get("seal_hash") != expected:
                        return False
                    prev = s.get("seal_hash", "")
            return True
        except Exception as e:
            self.logger.warning(f"verify_chain failed: {e}")
            return False

    @staticmethod
    def extract_evidence_refs(tool_results: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Derive court-usable provenance handles from the turn's tool results.

        - query_database  -> {database, sql, row_count, forensic_markers}
        - search_artifacts -> {database, table, rowids, forensic_markers}
        - analyze_large_dataset -> {target, results}
        - list_case_files -> {files_count}
        - query_correlation_results -> {results_count, forensic_markers}
        """
        refs: List[Dict[str, Any]] = []
        for r in (tool_results or []):
            name = r.get("tool_name") or r.get("name") or ""
            inner = r.get("result") if isinstance(r.get("result"), dict) else r

            if name == "query_database" or (isinstance(inner, dict) and inner.get("database_name") and inner.get("data") is not None):
                rows = inner.get("data") or inner.get("rows") or []
                ref = {
                    "tool": "query_database",
                    "database": inner.get("database_name"),
                    "sql": inner.get("sql_query") or inner.get("query"),
                    "row_count": inner.get("row_count", len(rows) if isinstance(rows, list) else None),
                }
                markers = EvidenceSeal._extract_row_metadata(rows if isinstance(rows, list) else [])
                if markers:
                    ref["forensic_markers"] = markers[:100]
                refs.append(ref)

            elif name == "search_artifacts":
                results = inner.get("results") if isinstance(inner, dict) else None
                if isinstance(results, dict):
                    for table, matches in results.items():
                        ref = {
                            "tool": "search_artifacts",
                            "table": table,
                            "row_count": len(matches or []),
                        }
                        markers = EvidenceSeal._extract_row_metadata(matches or [])
                        if markers:
                            db = markers[0].get("database") if markers else None
                            ref["database"] = db
                            ref["forensic_markers"] = markers[:100]
                        refs.append(ref)
                elif isinstance(results, list):
                    refs.append({
                        "tool": "search_artifacts",
                        "row_count": len(results),
                        "forensic_markers": EvidenceSeal._extract_row_metadata(results)[:100]
                    })

            elif name == "analyze_large_dataset":
                refs.append({
                    "tool": "analyze_large_dataset",
                    "target": inner.get("target"),
                    "results_summary": str(inner.get("results"))[:500] if inner.get("results") else None
                })

            elif name == "list_case_files":
                files = inner.get("files", [])
                refs.append({
                    "tool": "list_case_files",
                    "files_count": len(files) if isinstance(files, list) else 0
                })
            
            elif name == "query_correlation_results":
                results = inner.get("results") or []
                refs.append({
                    "tool": "query_correlation_results",
                    "row_count": len(results),
                    "forensic_markers": EvidenceSeal._extract_row_metadata(results)[:100]
                })

            elif name == "query_timeline":
                # A chronology sweep returns rows from several databases at
                # once, so the window and which artifacts were reached are part
                # of the provenance: "nothing happened then" is a claim about
                # what was searched, and without `artifacts_searched` there is
                # no record of whether a database was absent or simply empty.
                #
                # The exactness split is recorded too. A key upper bound cannot
                # support "X happened at T", and a reader of the sealed record
                # has to be able to see which rows were which.
                events = inner.get("events") or []
                bounded = [e for e in events
                           if isinstance(e, dict)
                           and e.get("exactness") != "exact"]
                refs.append({
                    "tool": "query_timeline",
                    "window": inner.get("window"),
                    "row_count": len(events),
                    "total_in_window": inner.get("total_in_window"),
                    "artifacts_searched": inner.get("artifacts_searched"),
                    "databases_absent": inner.get("databases_absent"),
                    "bounded_rows": len(bounded),
                    "forensic_markers":
                        EvidenceSeal._extract_row_metadata(events)[:100],
                })
            
            else:
                # Generic fallback for other investigative tools: scan result text for artifacts
                result_str = str(inner)
                artifacts = EvidenceSeal.extract_offsets_from_text(result_str)
                if artifacts:
                    refs.append({
                        "tool": name or "unknown",
                        "forensic_markers": artifacts[:50]
                    })
                    
        return refs

    @staticmethod
    def _extract_row_metadata(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract forensic markers (RN, EID, RowID, Offsets, Paths) from a list of result rows."""
        out = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            
            # 1. MFT / NTFS
            rn = row.get("record_number") or row.get("mft_entry") or row.get("mft_reference")
            if isinstance(rn, int):
                key = f"rn:{rn}"
                if key not in seen:
                    seen.add(key)
                    out.append({"type": "MFT_RECORD", "record_number": rn, "record_size": EvidenceSeal.MFT_RECORD_SIZE, "computed_file_offset": rn * EvidenceSeal.MFT_RECORD_SIZE, "label": f"RN:{rn}"})

            # 2. Event Logs
            eid = row.get("event_record_id") or row.get("event_id") or row.get("EventID")
            if isinstance(eid, int):
                key = f"eid:{eid}"
                if key not in seen:
                    seen.add(key)
                    out.append({"type": "EVENT_ID", "event_id": eid, "label": f"EID:{eid}"})

            # 3. Database Rows
            rowid = row.get("rowid") or row.get("row_id") or row.get("id")
            if isinstance(rowid, int):
                key = f"row:{rowid}"
                if key not in seen:
                    seen.add(key)
                    out.append({"type": "DB_ROW", "row_id": rowid, "label": f"ROW:{rowid}"})

            # 4. Physical Offsets
            off = row.get("offset") or row.get("phys_offset") or row.get("file_pos") or row.get("byte_pos")
            if isinstance(off, int):
                key = f"off:{off}"
                if key not in seen:
                    seen.add(key)
                    out.append({"type": "FILE_OFFSET", "computed_file_offset": off, "label": f"OFF:0x{off:X}"})

            # 5. Network (IPs)
            ip = row.get("ip_address") or row.get("source_ip") or row.get("dest_ip") or row.get("remote_host")
            if isinstance(ip, str) and len(ip) > 6:
                if ip not in seen:
                    seen.add(ip)
                    out.append({"type": "NETWORK_IP", "ip": ip, "label": f"IP:{ip}"})

            # 6. Paths
            path = row.get("file_path") or row.get("full_path") or row.get("key_path") or row.get("path")
            if isinstance(path, str) and len(path) > 3:
                if path not in seen:
                    seen.add(path)
                    label = path.split('\\')[-1] or path.split('/')[-1]
                    if len(label) > 20: label = label[:17] + "..."
                    out.append({"type": "PATH", "path": path, "label": f"PATH:{label}"})
            
            # 7. Forensic Hashes (SHA1) - Amcache
            sha1 = row.get("sha1") or row.get("hash_sha1") or row.get("Sha1")
            if isinstance(sha1, str) and len(sha1) == 40:
                if sha1 not in seen:
                    seen.add(sha1)
                    out.append({"type": "SHA1_HASH", "hash": sha1, "label": f"SHA1:{sha1[:8]}"})

            # 8. SRUM / Amcache App IDs
            aid = row.get("app_id") or row.get("application_id") or row.get("AppID")
            if isinstance(aid, int):
                key = f"app:{aid}"
                if key not in seen:
                    seen.add(key)
                    out.append({"type": "APP_ID", "app_id": aid, "label": f"APP:{aid}"})

            # 9. USN Journal Sequence
            usn = row.get("usn") or row.get("sequence_number") or row.get("Usn")
            if isinstance(usn, int):
                key = f"usn:{usn}"
                if key not in seen:
                    seen.add(key)
                    out.append({"type": "USN_SEQ", "usn": usn, "label": f"USN:{usn}"})

            # Limit per turn to avoid log bloat
            if len(out) >= 100: break
            
        return out

    @staticmethod
    def extract_offsets_from_text(text: str) -> List[Dict[str, Any]]:
        """Scan arbitrary text (e.g. cut/truncated content) for forensic artifacts
        including record numbers, file offsets, event IDs, network markers, and paths.
        
        Supports MFT (RN), Event Logs (EID), SQLite (Row), and Network (IP/Domain).
        """
        if not text or not isinstance(text, str):
            return []
        import re

        # Bound the regex sweep for very large content: scan the head + tail
        # (where markers cluster around the cut boundary) rather than the whole
        # multi-MB blob. The complete bytes remain in the sidecar for review.
        cap = EvidenceSeal.OFFSET_SCAN_MAX_CHARS
        if len(text) > cap:
            text = text[:cap] + "\n" + text[-cap:]

        seen = set()
        out = []

        # 1. Match Record Numbers (RN, record_number, record_id, rec_num)
        rn_patterns = [r'\b(?:record_number|rn|record_id|rec_num)\b[\s"\'\:\\\=]*(\d+)']
        for pat in rn_patterns:
            for match in re.findall(pat, text, re.IGNORECASE):
                try:
                    rn = int(match)
                    offset = rn * EvidenceSeal.MFT_RECORD_SIZE
                    key = f"rn:{rn}"
                    if key not in seen:
                        seen.add(key)
                        out.append({
                            "type": "MFT_RECORD",
                            "record_number": rn,
                            "record_size": EvidenceSeal.MFT_RECORD_SIZE,
                            "computed_file_offset": offset,
                            "label": f"RN:{rn}"
                        })
                except Exception: pass

        # 2. Match Direct Offsets (offset, file_pos, phys_offset, byte_pos)
        off_patterns = [r'\b(?:computed_file_offset|offset|file_pos|phys_offset|byte_pos)\b[\s"\'\:\\\=]*(\d+)']
        for pat in off_patterns:
            for match in re.findall(pat, text, re.IGNORECASE):
                try:
                    cfo = int(match)
                    key = f"off:{cfo}"
                    if key not in seen:
                        seen.add(key)
                        out.append({
                            "type": "FILE_OFFSET",
                            "computed_file_offset": cfo,
                            "label": f"OFF:0x{cfo:X}"
                        })
                except Exception: pass

        # 3. Match Event IDs (event_id, event_record_id, log_id)
        eid_patterns = [r'\b(?:event_record_id|event_id|log_id|eid)\b[\s"\'\:\\\=]*(\d+)']
        for pat in eid_patterns:
            for match in re.findall(pat, text, re.IGNORECASE):
                try:
                    eid = int(match)
                    key = f"eid:{eid}"
                    if key not in seen:
                        seen.add(key)
                        out.append({
                            "type": "EVENT_ID",
                            "event_id": eid,
                            "label": f"EID:{eid}"
                        })
                except Exception: pass

        # 4. Match Database Row IDs (rowid, row_id)
        row_patterns = [r'\b(?:rowid|row_id)\b[\s"\'\:\\\=]*(\d+)']
        for pat in row_patterns:
            for match in re.findall(pat, text, re.IGNORECASE):
                try:
                    row = int(match)
                    key = f"row:{row}"
                    if key not in seen:
                        seen.add(key)
                        out.append({
                            "type": "DB_ROW",
                            "row_id": row,
                            "label": f"ROW:{row}"
                        })
                except Exception: pass

        # 5. Network Artifacts (IPv4) — validate octets to avoid matching version
        # strings / invalid addresses (e.g. 999.999.999.999, 1.2.3.4 build nums).
        ipv4_pat = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        for match in re.findall(ipv4_pat, text):
            if match in seen:
                continue
            octets = match.split(".")
            if len(octets) != 4 or any(int(o) > 255 for o in octets):
                continue
            seen.add(match)
            out.append({
                "type": "NETWORK_IP",
                "ip": match,
                "label": f"IP:{match}"
            })

        # 6. Path Artifacts (Registry & File Paths)
        # Registry
        reg_pat = r'\b(HKEY_[A-Z_]+\\[^"\'\s,;]+|HKLM\\[^"\'\s,;]+|HKCU\\[^"\'\s,;]+)'
        for match in re.findall(reg_pat, text, re.IGNORECASE):
            if match not in seen:
                seen.add(match)
                label = match.split('\\')[-1]
                if len(label) > 20: label = label[:17] + "..."
                out.append({"type": "REGISTRY_KEY", "path": match, "label": f"REG:{label}"})
        
        # Files (C:\...)
        file_pat = r'\b([a-z]:\\[^"\'\s,;<>|]+)'
        for match in re.findall(file_pat, text, re.IGNORECASE):
            if match not in seen:
                seen.add(match)
                label = match.split('\\')[-1]
                if len(label) > 20: label = label[:17] + "..."
                out.append({"type": "PATH", "path": match, "label": f"PATH:{label}"})

        # 7. SHA-1 Hashes (Amcache, File identification)
        sha1_pat = r'\b([0-9a-f]{40})\b'
        for match in re.findall(sha1_pat, text, re.IGNORECASE):
            if match not in seen:
                seen.add(match)
                out.append({
                    "type": "SHA1_HASH",
                    "hash": match,
                    "label": f"SHA1:{match[:8]}"
                })

        # 8. USN Journal / Sequence Numbers
        usn_pat = r'\b(?:usn|seq_num|sequence_number|journal sequence)\b[\s"\'\:\\\=]*(\d+)'
        for match in re.findall(usn_pat, text, re.IGNORECASE):
            try:
                seq = int(match)
                key = f"usn:{seq}"
                if key not in seen:
                    seen.add(key)
                    out.append({
                        "type": "USN_SEQ",
                        "usn": seq,
                        "label": f"USN:{seq}"
                    })
            except Exception: pass

        # 9. App IDs (SRUM, Amcache)
        app_pat = r'\b(?:app_id|application id|application_id)\b[\s"\'\:\\\=]*(\d+)'
        for match in re.findall(app_pat, text, re.IGNORECASE):
            try:
                aid = int(match)
                key = f"app:{aid}"
                if key not in seen:
                    seen.add(key)
                    out.append({
                        "type": "APP_ID",
                        "app_id": aid,
                        "label": f"APP:{aid}"
                    })
            except Exception: pass
                
        return out[:100]

    @staticmethod
    def _redact(text: str) -> str:
        if not isinstance(text, str):
            return text
        import re
        return re.sub(r'\bAIzaSy[A-Za-z0-9_\-]{33}\b', '[REDACTED_API_KEY]', text)

    def spill_dropped_payload(self, text: str) -> Dict[str, Any]:
        """Write the COMPLETE dropped/processed bytes to a per-hash sidecar file
        so the full content is recoverable even though the seal keeps only a
        bounded preview inline.

        Self-consistent: the returned ``sha256`` is the hash of EXACTLY the bytes
        written to the sidecar and the file is named after that same hash, so a
        verifier can recompute it directly. Callers are responsible for passing
        already-sanitized (redacted) text — this method does not alter the bytes.

        Returns ``{sha256, len, sidecar}`` where ``sidecar`` is the path relative
        to ``EYE_Logs`` (e.g. ``dropped_payloads/<sha>.txt``) or ``None`` if it
        could not be written. Best-effort: never raises into the investigation
        pipeline. Dedups by hash (identical content is written once).
        """
        text = text or ""
        sha = self._sha256(text)
        info: Dict[str, Any] = {"sha256": sha, "len": len(text), "sidecar": None}
        if not self._spill_dir:
            return info
        try:
            self._spill_dir.mkdir(parents=True, exist_ok=True)
            out_path = self._spill_dir / f"{sha}.txt"
            if not out_path.exists():
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(text)
            info["sidecar"] = f"dropped_payloads/{sha}.txt"
        except Exception as e:
            self.logger.warning(f"Could not spill dropped payload to sidecar: {e}")
        return info

    def _compress_payload(self, sha: str) -> None:
        """Compress one sealed-payload sidecar (best-effort)."""
        if self._payload_dir and sha:
            _compress_file_to_variant(self._payload_dir / f"{sha}.txt")

    def _seed_recent_payloads(self) -> None:
        """On startup, rebuild the recency window from the seal log and compress
        any sealed payload older than the most recent N (so a session that ended
        before compacting still gets its old payloads compressed)."""
        try:
            order: List[str] = []
            if self._log_path and self._log_path.exists():
                with open(self._log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        if rec.get("payload_sidecar") and rec.get("payload_sha256"):
                            order.append(rec["payload_sha256"])
            n = self._recent_uncompressed
            self._recent_payload_shas = order[-n:] if n > 0 else []
            for sha in (order[:-n] if n > 0 else order):
                self._compress_payload(sha)
        except Exception as e:
            self.logger.warning(f"Could not seed sealed-payload recency window: {e}")

    def spill_sealed_payload(self, text: str, sha: Optional[str] = None) -> Optional[str]:
        """Persist the FULL (already-redacted) payload the model saw to a per-hash
        sidecar so each seal is independently reproducible. Dedups by hash. Keeps
        the most recent ``_recent_uncompressed`` payloads as plain ``.txt`` and
        compresses the one that falls out of that window (zstd, gzip fallback).

        Returns the stable logical ref ``sealed_payloads/<sha>.txt`` (the reader
        resolves the actual compressed variant), or None if not stored.
        Best-effort: never raises into the investigation pipeline."""
        if not self._payload_dir:
            return None
        text = text or ""
        sha = sha or self._sha256(text)
        try:
            self._payload_dir.mkdir(parents=True, exist_ok=True)
            base = self._payload_dir / f"{sha}.txt"
            # Write once (dedup across .txt / .txt.zst / .txt.gz variants).
            if not (base.exists() or Path(str(base) + ".zst").exists() or Path(str(base) + ".gz").exists()):
                with open(base, "w", encoding="utf-8") as f:
                    f.write(text)
            # Recency window: move this sha to most-recent; compress the evictee.
            if sha in self._recent_payload_shas:
                self._recent_payload_shas.remove(sha)
            self._recent_payload_shas.append(sha)
            if len(self._recent_payload_shas) > self._recent_uncompressed:
                evicted = self._recent_payload_shas.pop(0)
                if evicted != sha:
                    self._compress_payload(evicted)
            return f"sealed_payloads/{sha}.txt"
        except Exception as e:
            self.logger.warning(f"Could not spill sealed payload to sidecar: {e}")
            return None

    def read_sealed_payload(self, sha: str) -> Optional[str]:
        """Return the full sealed payload plaintext for ``sha`` (decompressing as
        needed), or None. The plaintext re-hashes to the seal's payload_sha256."""
        if not self._payload_dir:
            return None
        return read_payload_sidecar(self._payload_dir, sha)

    def build_cut_detail(
        self,
        *,
        action: str,
        message_id: Optional[str],
        role: Optional[str],
        original_text: str,
        processed_text: str,
        dropped_text: str,
        token_count: Optional[int] = None,
        iteration: Optional[int] = None,
        processed_is_prefix: bool = False,
    ) -> Dict[str, Any]:
        """Build one canonical cut_detail record shared by every cut site
        (self-heal summarize, self-heal drop, tool-output cap).

        Captures, for both the surviving and dropped portions:
          - the real content (``processed_content`` / ``cut_content``) bounded to
            ``CUT_PREVIEW_CHARS`` inline, with the full bytes spilled to a sidecar;
          - forensic-artifact offsets found in each portion
            (``processed_file_offsets`` / ``dropped_file_offsets``);
          - the explicit character range of the cut within the original message
            (``cut_range``: which chars were kept vs dropped).

        FORENSIC INTEGRITY: every recorded copy describes the **redacted**
        artifact. The texts are sanitized once up front, and the hashes, lengths,
        inline previews, offset scans, and sidecars are all derived from that same
        redacted text — so a verifier recomputing the SHA-256 of a sidecar (or the
        inline preview, when it holds the whole portion) gets exactly the recorded
        ``*_sha256``. Hashing un-redacted text while storing redacted bytes would
        make the seal unverifiable.

        ``processed_is_prefix`` tells the range logic whether the survivor is a
        literal head slice of the original (tool-output cap) or a replacement
        (a summary, or an outright drop). It is authoritative — we never infer it
        from ``startswith``, which a secret straddling the cut boundary could
        break after redaction.
        """
        # Sanitize once; everything below describes these redacted bytes.
        original_text = self._redact(original_text or "")
        processed_text = self._redact(processed_text or "")
        dropped_text = self._redact(dropped_text or "")

        cap = self.CUT_PREVIEW_CHARS

        def portion_info(text: str) -> Dict[str, Any]:
            # Only spill to a sidecar when the content exceeds the inline cap;
            # otherwise the inline preview already holds every byte. The text is
            # already redacted, so spill (which hashes exactly what it writes)
            # produces a hash that matches this sha256.
            info = {"sha256": self._sha256(text), "len": len(text), "sidecar": None}
            if len(text) > cap:
                info["sidecar"] = self.spill_dropped_payload(text).get("sidecar")
            return info

        cut_spill = portion_info(dropped_text)
        proc_spill = portion_info(processed_text)

        # Character range of the cut within the original (redacted) message. For a
        # tool-output cap the kept head is processed_text and the dropped tail
        # starts right after it; for a summary/outright drop there is no kept
        # prefix so the dropped span covers the whole message. total is derived as
        # kept_end + len(dropped) so cut_range.dropped length == cut_content_len.
        kept_end = len(processed_text) if processed_is_prefix else 0
        total = kept_end + len(dropped_text)
        cut_range = {
            "unit": "chars",
            "total": total,
            "processed": [0, kept_end],
            "dropped": [kept_end, total],
        }

        return {
            "action": action,
            "message_id": message_id,
            "role": role,
            "iteration": iteration,
            "token_count": token_count,
            "sha256": self._sha256(original_text),
            "cut_range": cut_range,
            # Bounded inline previews (full bytes live in the sidecars below).
            "cut_content": dropped_text[:cap],
            "cut_content_len": cut_spill["len"],
            "cut_content_sha256": cut_spill["sha256"],
            "cut_content_sidecar": cut_spill["sidecar"],
            "processed_content": processed_text[:cap],
            "processed_content_len": proc_spill["len"],
            "processed_content_sha256": proc_spill["sha256"],
            "processed_content_sidecar": proc_spill["sidecar"],
            "processed_file_offsets": EvidenceSeal.extract_offsets_from_text(processed_text),
            "dropped_file_offsets": EvidenceSeal.extract_offsets_from_text(dropped_text),
        }

    def seal(
        self,
        payload_text: str,
        *,
        phase: str,
        iteration: Optional[int],
        query: str,
        model: str,
        max_context: int,
        token_count: int,
        evidence_refs: Optional[List[Dict[str, Any]]] = None,
        truncated: bool = False,
        cut_details: Optional[List[Dict[str, Any]]] = None,
        sent_to_model: bool = True,
        force_full_payload: bool = False,
    ) -> Dict[str, Any]:
        """Seal one exact LLM payload and append it to the chain. Best-effort:
        never raises into the investigation pipeline.

        ``sent_to_model`` is False for a payload that was assembled and sealed but
        then REFUSED (over the context limit) — so the chain records what we
        declined to send, and the self-heal cuts that occurred, not only payloads
        the model actually saw."""
        payload_text = EvidenceSeal._redact(payload_text)
        query = EvidenceSeal._redact(query)
        
        # Deep redaction for metadata to prevent secret leakage in logs
        if cut_details:
            try:
                cut_details_str = json.dumps(cut_details, default=str)
                redacted_cut_details_str = EvidenceSeal._redact(cut_details_str)
                cut_details = json.loads(redacted_cut_details_str)
            except Exception:
                pass
                
        if evidence_refs:
            try:
                evidence_refs_str = json.dumps(evidence_refs, default=str)
                redacted_evidence_refs_str = EvidenceSeal._redact(evidence_refs_str)
                evidence_refs = json.loads(redacted_evidence_refs_str)
            except Exception:
                pass

        payload_sha256 = self._sha256(payload_text)

        # FORENSIC INTEGRITY: The seal_hash MUST protect the entire record,
        # including metadata and provenance. We fold a canonical summary of
        # the inputs into the hash to ensure non-repudiation for the entire entry.
        metadata_summary = f"{phase}|{iteration}|{query}|{model}|{max_context}|{token_count}|" \
                          f"{json.dumps(evidence_refs or [], sort_keys=True)}|" \
                          f"{json.dumps(cut_details or [], sort_keys=True)}|" \
                          f"{int(bool(sent_to_model))}"
        metadata_sha256 = self._sha256(metadata_summary)

        # Serialize the sequence bump, hash-chain link, and append. Without this
        # lock two concurrent seals could read the same prev_seal_hash and fork
        # the chain. (A single case directory should still have one writer; this
        # is defense in depth.) Note: a single case dir must use one EvidenceSeal.
        with self._lock:
            # Compute the next seq/hash LOCALLY; only commit them to the instance
            # AFTER a successful disk append, so a write failure never leaves the
            # in-memory chain pointing past a record that isn't on disk (which
            # would make every subsequent record appear to break the chain).
            new_seq = self._seq + 1
            prev_seal_hash = self._prev_seal_hash
            # The chain folds the previous hash + payload hash + metadata hash
            seal_hash = self._sha256(prev_seal_hash + payload_sha256 + metadata_sha256)
            # Persist the full (redacted) payload so the seal is independently
            # reproducible. The sidecar's content hashes to payload_sha256 (already
            # in seal_hash), so it is tamper-evident; not folded into the chain
            # math (it is derivable), keeping existing chain verification intact.
            # A REFUSED payload is exceptional integrity evidence — always spill it
            # (force_full_payload) even if routine full-payload storage is off, so
            # the original message is reliably in the data.
            payload_sidecar = (
                self.spill_sealed_payload(payload_text, sha=payload_sha256)
                if (self.store_full_payload or force_full_payload) else None
            )
            record = {
                "seq": new_seq,
                "timestamp": datetime.now().isoformat(),
                "phase": phase,
                "iteration": iteration,
                "query": query,
                "model": model,
                "max_context_tokens": max_context,
                "payload_tokens": token_count,
                "truncated": bool(truncated),
                "sent_to_model": bool(sent_to_model),
                "cut_details": cut_details or [],
                "payload_sha256": payload_sha256,
                "payload_sidecar": payload_sidecar,
                # Bounded inline copy of the ORIGINAL message for a refused payload,
                # so the Compliance UI can show what was refused without a sidecar
                # round-trip. Derivable from the payload (like the sidecar); not
                # folded into the hash chain, so verification is unaffected.
                "payload_preview": (payload_text[:self.CUT_PREVIEW_CHARS] if not sent_to_model else None),
                "metadata_sha256": metadata_sha256,
                "prev_seal_hash": prev_seal_hash,
                "seal_hash": seal_hash,
                "evidence_refs": evidence_refs or [],
            }
            wrote = False
            try:
                if self._log_path:
                    self._log_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self._log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    wrote = True
            except Exception as e:
                self.logger.error(f"Failed to write evidence seal: {e}")
            # Commit the chain pointer ONLY if the record was persisted (or there
            # is no on-disk log to stay consistent with). On a write failure we
            # leave _seq/_prev_seal_hash untouched so the next seal retries the
            # same link instead of stranding the chain ahead of disk.
            if wrote or not self._log_path:
                self._seq = new_seq
                self._prev_seal_hash = seal_hash
        return record
