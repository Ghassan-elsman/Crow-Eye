"""Deleted files recovered from their MFT record, into the case.

A deleted file's $MFT record usually survives its deletion: NTFS clears the
record's in-use flag and frees its clusters in $Bitmap, but leaves the record
- its names, times and data runs - where it was until the record is reused.
While that holds, the file's bytes can be read back through the runs, the
same way the MFT parser reads the $MFT itself (utils/ntfs_runs). That is what
this module does, on any NTFS volume Crow-Eye can read raw: this machine's
volume (administrator), a partition of a forensic image, or a shadow copy
rebuilt by Crow-Eye's own VSS reader. One code path, shared by the desktop's
File Browser and the Sentinel agent (Ghassan, 2026-11-01).

WHAT IS CHECKED BEFORE A BYTE IS COPIED
  * The record is still a deleted file: in use again means the record now
    belongs to another file, and nothing is recovered.
  * Its sequence number is the one the listing showed: a record freed,
    reused and freed again since the listing was made holds another file.
  * Its $DATA can be read: a compressed or encrypted stream is refused with
    the reason, never written out as garbage.

WHAT THE INVESTIGATOR IS TOLD ABOUT THE RESULT
  The clusters a deleted file used are free, so the volume may have written
  new data over them since. Each cluster run is checked against the volume's
  $Bitmap as it is now: a cluster allocated again may hold another file's
  bytes. The file is still recovered - it is the investigator's call - but
  the record, the manifest and the custody entry say how many of its clusters
  are in use now ("may be overwritten"). A sparse run reads as zeros, as NTFS
  reads it; bytes past the stream's initialised size read as zeros too.

    vol = NtfsVolume(stream)                          # any seekable volume
    info = carve(vol, record, sequence, dest_path)    # one file
    result = recover_deleted(case_root, stream, label, tag, items)   # into the case
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import struct
import io
from typing import Callable, Dict, List, Optional

from utils.ntfs_runs import (RunMap, apply_fixups, attribute_stream, decode_runlist,
                             mft_layout, nonresident_header, read_stream)

logger = logging.getLogger(__name__)

ATTR_ATTRIBUTE_LIST = 0x20
ATTR_FILE_NAME = 0x30
ATTR_DATA = 0x80
END = 0xFFFFFFFF
FLAG_IN_USE = 0x0001
FLAG_DIRECTORY = 0x0002
DATA_COMPRESSED = 0x0001
DATA_ENCRYPTED = 0x4000
BITMAP_RECORD = 6
CHUNK = 4 * 1024 * 1024
# Read into memory before anything is written, up to these sizes: on the volume
# being recovered from, the case's own new files (its folder, manifest, custody
# record) take the records and clusters NTFS has just freed - the deleted files'
# own - within moments. Measured on this machine's C:, 2026-11-01: both records
# of two files deleted a second earlier were reused before the recovery reached
# them. Larger files are streamed after, with that said in their record.
MEMORY_PER_FILE = 256 * 1024 * 1024
MEMORY_TOTAL = 1024 * 1024 * 1024
RECOVERY_DIR = "app_acquisition"          # beside acquisitions: one place for collected files


class RecoveryError(ValueError):
    """A recovery refused, in words for the investigator."""


class NtfsVolume:
    """An NTFS volume over a seekable stream: its boot sector, its $MFT mapped
    through its own runs, and its $Bitmap read on demand."""

    def __init__(self, stream):
        self.f = stream
        boot = self.read_at(0, 512)
        if boot[3:11] != b"NTFS    ":
            raise RecoveryError("not an NTFS volume")
        self.sector = struct.unpack_from("<H", boot, 11)[0] or 512
        self.cluster = self.sector * boot[13]
        self.mft_lcn = struct.unpack_from("<Q", boot, 48)[0]
        per_record = struct.unpack_from("<b", boot, 64)[0]
        self.record_size = (per_record * self.cluster if per_record > 0
                            else 1 << (-per_record))
        self.serial = struct.unpack_from("<Q", boot, 0x48)[0]
        self.mft, self.mft_size, _alloc = mft_layout(self.read_at, self.mft_lcn,
                                                     self.cluster, self.record_size)
        self._bitmap = None

    def read_at(self, offset: int, length: int) -> bytes:
        self.f.seek(offset)
        out = bytearray()
        while len(out) < length:
            part = self.f.read(length - len(out))
            if not part:
                break
            out += part
        return bytes(out)

    def raw_record(self, number: int) -> bytes:
        if number < 0 or (number + 1) * self.record_size > self.mft_size:
            raise RecoveryError("record %d is past the end of the $MFT" % number)
        raw = read_stream(self.read_at, self.mft, number * self.record_size, self.record_size)
        if raw[:4] != b"FILE":
            raise RecoveryError("record %d holds no FILE record" % number)
        rec, _ok = apply_fixups(raw)
        return rec

    def _bitmap_map(self):
        if self._bitmap is None:
            content, runs, header = attribute_stream(self.raw_record(BITMAP_RECORD), ATTR_DATA)
            if content is not None:
                self._bitmap = ("resident", content)
            elif runs:
                self._bitmap = ("runs", RunMap(runs, self.cluster))
            else:
                raise RecoveryError("the volume's $Bitmap cannot be read")
        return self._bitmap

    def clusters_in_use(self, lcn: int, count: int) -> int:
        """How many of ``count`` clusters from ``lcn`` the volume marks in use now."""
        kind, src = self._bitmap_map()
        first, last = lcn // 8, (lcn + count - 1) // 8
        data = (src[first:last + 1] if kind == "resident"
                else read_stream(self.read_at, src, first, last - first + 1))
        used = 0
        for c in range(lcn, lcn + count):
            byte = data[c // 8 - first] if c // 8 - first < len(data) else 0
            used += (byte >> (c % 8)) & 1
        return used


def _attributes(rec: bytes):
    off = struct.unpack_from("<H", rec, 0x14)[0]
    while off + 16 <= len(rec):
        a_type, a_len = struct.unpack_from("<II", rec, off)
        if a_type == END or a_len == 0 or off + a_len > len(rec):
            return
        name_len = rec[off + 9]
        name_off = struct.unpack_from("<H", rec, off + 10)[0]
        name = rec[off + name_off:off + name_off + 2 * name_len].decode("utf-16le", "replace") \
            if name_len else ""
        yield a_type, off, a_len, rec[off + 8], name
        off += a_len


def _file_name(rec: bytes) -> str:
    """The record's long name (Win32 or POSIX before the DOS 8.3 alias)."""
    best, best_ns = "", None
    for a_type, off, _len, non_res, _n in _attributes(rec):
        if a_type != ATTR_FILE_NAME or non_res:
            continue
        v_off = struct.unpack_from("<H", rec, off + 0x14)[0]
        body = rec[off + v_off:]
        n_len, ns = body[0x40], body[0x41]
        name = body[0x42:0x42 + 2 * n_len].decode("utf-16le", "replace")
        if best_ns is None or (best_ns == 2 and ns != 2):
            best, best_ns = name, ns
    return best


def _data_segments(vol: NtfsVolume, rec: bytes, number: int):
    """(resident content or None, runs, header of VCN 0, flags) of the
    unnamed $DATA, its extension segments included."""
    runs, header, flags, more = [], None, 0, []
    content = None
    for a_type, off, a_len, non_res, name in _attributes(rec):
        if a_type == ATTR_DATA and not name:
            flags |= struct.unpack_from("<H", rec, off + 0x0C)[0]
            if not non_res:
                v_len, v_off = struct.unpack_from("<IH", rec, off + 0x10)
                content = rec[off + v_off:off + v_off + v_len]
            else:
                h = nonresident_header(rec, off)
                runs.extend(decode_runlist(rec[off:off + a_len], h["runlist_offset"],
                                           h["first_vcn"]))
                if h["first_vcn"] == 0:
                    header = h
        elif a_type == ATTR_ATTRIBUTE_LIST and not non_res:
            v_len, v_off = struct.unpack_from("<IH", rec, off + 0x10)
            body = rec[off + v_off:off + v_off + v_len]
            p = 0
            while p + 26 <= len(body):
                e_type, e_len = struct.unpack_from("<IH", body, p)
                if e_len == 0:
                    break
                ref = struct.unpack_from("<Q", body, p + 16)[0] & 0xFFFFFFFFFFFF
                if e_type == ATTR_DATA and body[p + 6] == 0 and ref != number:
                    more.append(ref)
                p += e_len
    for ref in sorted(set(more)):
        try:
            ext = vol.raw_record(ref)
        except RecoveryError:
            raise RecoveryError("a piece of the file's run list (record %d) is gone" % ref)
        base = struct.unpack_from("<Q", ext, 0x20)[0] & 0xFFFFFFFFFFFF
        if base != number:
            raise RecoveryError("a piece of the file's run list (record %d) now belongs "
                                "to another file" % ref)
        _c, ext_runs, ext_h, ext_flags = _data_segments(vol, ext, ref)
        runs.extend(ext_runs)
        flags |= ext_flags
        if header is None and ext_h is not None and ext_h["first_vcn"] == 0:
            header = ext_h
    return content, runs, header, flags


def inspect(vol: NtfsVolume, number: int, sequence: Optional[int] = None,
            expect_name: Optional[str] = None) -> dict:
    """What recovering record ``number`` would give, without writing: name,
    size, clusters, how many are in use now. Raises RecoveryError when it
    cannot be recovered."""
    rec = vol.raw_record(number)
    seq = struct.unpack_from("<H", rec, 0x10)[0]
    flags = struct.unpack_from("<H", rec, 0x16)[0]
    if flags & FLAG_IN_USE:
        raise RecoveryError("record %d is in use again: it now holds another file, so the "
                            "deleted one cannot be recovered from it" % number)
    if sequence is not None and int(sequence) != seq:
        raise RecoveryError("record %d was reused since the listing was made (sequence %d, "
                            "the listing had %d): the deleted file is gone"
                            % (number, seq, int(sequence)))
    if expect_name:
        # Before the folder test: a record that now holds a different name was
        # reused (or is on another volume), whatever it holds now.
        held = _file_name(rec)
        if held and held.lower() != expect_name.lower():
            raise RecoveryError("record %d now holds '%s', not '%s': it was reused since the file "
                                "was deleted, or the volume read is not the one the listing came "
                                "from" % (number, held, expect_name))
    if flags & FLAG_DIRECTORY:
        raise RecoveryError("record %d is a folder: recover the files in it" % number)
    content, runs, header, data_flags = _data_segments(vol, rec, number)
    if data_flags & DATA_ENCRYPTED:
        raise RecoveryError("the file was encrypted (EFS): its clusters hold ciphertext only")
    if data_flags & DATA_COMPRESSED:
        raise RecoveryError("the file was NTFS-compressed: compressed recovery is not supported")
    info = {"record": number, "sequence": seq, "name": _file_name(rec),
            "resident": content is not None, "clusters": 0, "clusters_in_use": 0,
            "sparse_clusters": 0}
    if content is not None:
        info["size"] = len(content)
        info["_content"] = content
        return info
    if header is None:
        raise RecoveryError("record %d holds no data for the file" % number)
    info["size"] = header["data_size"]
    info["initialized"] = header["initialized_size"]
    for _vcn, lcn, count in runs:
        info["clusters"] += count
        if lcn is None:
            info["sparse_clusters"] += count
        else:
            info["clusters_in_use"] += vol.clusters_in_use(lcn, count)
    info["_runs"] = runs
    info["_content"] = content
    return info


def _read_into(vol: NtfsVolume, info: dict, out, stop) -> dict:
    """Write the file inspect() described into ``out`` (any binary file object).
    Returns info with sha256, written and risk."""
    runs, content = info.pop("_runs", None), info.pop("_content", None)
    digest = hashlib.sha256()
    if info["resident"]:
        out.write(content)
        digest.update(content)
        written = len(content)
    else:
        runmap = RunMap(runs, vol.cluster)
        size, init = info["size"], info.get("initialized", info["size"])
        pos = 0
        while pos < size:
            if stop():
                raise RecoveryError("cancelled")
            n = min(CHUNK, size - pos)
            if pos >= init:
                block = b"\0" * n
            else:
                block = read_stream(vol.read_at, runmap, pos, min(n, init - pos))
                block += b"\0" * (n - len(block))
            out.write(block)
            digest.update(block)
            pos += n
        written = pos
    info.update(sha256=digest.hexdigest(), written=written, risk=risk_words(info))
    return info


def carve(vol: NtfsVolume, number: int, sequence: Optional[int], dest: str,
          is_cancelled: Optional[Callable[[], bool]] = None,
          expect_name: Optional[str] = None) -> dict:
    """Recover record ``number`` to ``dest``. Returns the inspect() facts plus
    sha256, written and risk (the words for the clusters in use now)."""
    stop = is_cancelled or (lambda: False)
    info = inspect(vol, number, sequence, expect_name)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as out:
        return _read_into(vol, info, out, stop)


def risk_words(info: dict) -> str:
    used = info.get("clusters_in_use", 0)
    real = info.get("clusters", 0) - info.get("sparse_clusters", 0)
    if info.get("resident"):
        return "whole: the file's bytes were inside its MFT record"
    if not real:
        return "whole: the file held no data clusters"
    if used == 0:
        return "no cluster reused: none of its %d cluster(s) is in use now" % real
    if used >= real:
        return ("may be overwritten: all %d of its cluster(s) are in use again, so the bytes "
                "may belong to another file" % real)
    return ("may be overwritten: %d of its %d cluster(s) are in use again, so part of the "
            "bytes may belong to another file" % (used, real))


def _slug(text: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", text or "").strip(" ._")
    return (s or "recovered")[:120]


def recover_deleted(case_root: str, stream, source_label: str, tag: str,
                    items: List[dict],
                    progress: Optional[Callable[[str, int, int], None]] = None,
                    is_cancelled: Optional[Callable[[], bool]] = None) -> dict:
    """Recover deleted files into the case, with custody.

    ``items``: [{"record", "sequence", "path"}] - path below the volume, as
    the listing showed it. Layout:

        <case>/app_acquisition/Recovered_<tag>_<UTC>/
            <tag>/<path>              each recovered file, path kept
            app_manifest.json         per file: record, sequence, SHA-256,
                                      clusters, in use now, the risk words

    Returns {folder, files, failed, errors, custody_record, entries}.
    """
    from .collector import _utc_now
    say = progress or (lambda _m, _d, _t: None)
    stop = is_cancelled or (lambda: False)
    started = _utc_now()
    entries, errors, failed = [], [], 0
    status = "completed"
    refused = []                     # (rel, item, reason) - recorded once custody is open
    read = []                        # (rel, item, info, buffer or None)
    vol = None
    # PHASE 1 - READ. Nothing is written anywhere until every file is read
    # (into memory, within the limits), so the recovery cannot take the very
    # records and clusters it is recovering from.
    try:
        vol = NtfsVolume(stream)
        logger.info("Deleted-file recovery: %d file(s) from %s (serial %016X, cluster %d B)",
                    len(items), source_label, vol.serial, vol.cluster)
        held = 0
        for n, item in enumerate(items, 1):
            if stop():
                status = "cancelled"
                break
            rel = (item.get("path") or "record_%s" % item.get("record")).replace("/", "\\").strip("\\")
            say("Reading %s" % rel, n, len(items))
            try:
                info = inspect(vol, int(item["record"]), item.get("sequence"),
                               rel.rsplit("\\", 1)[-1] if item.get("check_name") else None)
                buf = None
                if info["size"] <= MEMORY_PER_FILE and held + info["size"] <= MEMORY_TOTAL:
                    buf = io.BytesIO()
                    info = _read_into(vol, info, buf, stop)
                    held += info["written"]
                read.append((rel, item, info, buf))
            except (RecoveryError, OSError, struct.error) as exc:
                refused.append((rel, item, str(exc)))
    except (RecoveryError, OSError, ValueError) as exc:
        status = "failed"
        errors.append(str(exc))
        logger.error("Deleted-file recovery failed on %s: %s", source_label, exc)

    # PHASE 2 - WRITE, with custody.
    folder = os.path.join(case_root, RECOVERY_DIR, "Recovered_%s_%s" % (
        _slug(tag).replace(" ", "_"), started.strftime("%Y%m%dT%H%M%SZ")))
    files_root = os.path.join(folder, _slug(tag).replace(" ", "_"))
    os.makedirs(files_root, exist_ok=True)
    try:
        from utils import custody
    except Exception:
        custody = None
    rec = None
    if custody is not None:
        try:
            rec = custody.begin(case_root, "deleted file recovery", options={
                "source": source_label, "method": "mft_carve",
                "items": [{"record": i.get("record"), "sequence": i.get("sequence"),
                           "path": i.get("path")} for i in items]}, output_dir=folder)
        except Exception as exc:
            logger.warning("Chain-of-custody record not started: %s", exc)
    for rel, item, reason in refused:
        failed += 1
        errors.append("%s: %s" % (rel, reason))
        logger.warning("Not recovered: %s (record %s): %s", rel, item.get("record"), reason)
        if rec is not None:
            rec.add_failure("%s (record %s)" % (rel, item.get("record")), reason, method="mft_carve")
    for rel, item, info, buf in read:
        dest = os.path.join(files_root, *[_slug(p) for p in rel.split("\\") if p])
        if os.path.exists(dest):
            base, ext = os.path.splitext(dest)
            dest = "%s (record %s)%s" % (base, item.get("record"), ext)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            if buf is not None:
                with open(dest, "wb") as out:
                    out.write(buf.getvalue())
            else:
                # Too large to hold: read now, after the case's own files were
                # written - said in its record.
                with open(dest, "wb") as out:
                    info = _read_into(vol, info, out, stop)
                info["risk"] += "; read after the case's own files were written (too large to hold first)"
        except (RecoveryError, OSError, struct.error) as exc:
            failed += 1
            errors.append("%s: %s" % (rel, exc))
            logger.warning("Not recovered: %s (record %s): %s", rel, item.get("record"), exc)
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except OSError:
                    pass
            if rec is not None:
                rec.add_failure("%s (record %s)" % (rel, item.get("record")), str(exc), method="mft_carve")
            continue
        entry = {"path": rel, "copy": os.path.relpath(dest, folder), "size": info["written"],
                 "sha256": info["sha256"], "record": info["record"],
                 "sequence": info["sequence"], "name_in_record": info["name"],
                 "clusters": info["clusters"], "clusters_in_use": info["clusters_in_use"],
                 "sparse_clusters": info["sparse_clusters"], "resident": info["resident"],
                 "risk": info["risk"], "method": "mft_carve", "verified": None}
        entries.append(entry)
        logger.info("Recovered %s from record %d (sequence %d): %d bytes, SHA-256 %s; %s",
                    rel, info["record"], info["sequence"], info["written"], info["sha256"], info["risk"])
        if rec is not None:
            try:
                rec.add_output(dest, kind="recovered deleted file", note=(
                    "carved from $MFT record %d (sequence %d) of %s; %s"
                    % (info["record"], info["sequence"], source_label, info["risk"])))
            except Exception:
                pass
    if status == "completed" and (failed or not entries):
        status = "partial" if entries else "failed"
    custody_path = None
    if rec is not None:
        try:
            rec.data["recovery"] = {"files": len(entries), "failed": failed}
            custody_path = custody.end(status, rec)
        except Exception as exc:
            logger.error("Chain-of-custody record not written: %s", exc)
    manifest = {
        "format": "crow-eye deleted file recovery 1",
        "kind": "recovered", "source": source_label, "source_kind": "mft_carve",
        "started_utc": started.isoformat(), "finished_utc": _utc_now().isoformat(),
        "status": status, "totals": {"files": len(entries), "failed": failed},
        "errors": errors, "custody_record": custody_path, "files": entries,
    }
    with open(os.path.join(folder, "app_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, ensure_ascii=False, default=str)
    logger.info("Deleted-file recovery %s: %d recovered, %d not; custody %s",
                status, len(entries), failed, custody_path)
    return {"folder": folder, "files": len(entries), "failed": failed, "errors": errors,
            "custody_record": custody_path, "entries": entries, "status": status}


def open_volume(kind: str, **where):
    """A seekable stream over the volume a listing came from.

    kind "live": where["volume"] letter (administrator, raw);
    kind "image": where["image_path"], where["partition"];
    kind "image_shadow": plus where["store_index"];
    kind "hidden_shadow" / "shadow": where["volume"], where["shadow_id"].
    """
    from Artifacts_Collectors import shadow_copies as sc
    if kind == "live":
        return sc.raw_volume(where["volume"])
    if kind == "image":
        return sc.open_image_volume(where["image_path"], int(where["partition"]))[1]
    if kind == "image_shadow":
        _s, vol = sc.open_image_volume(where["image_path"], int(where["partition"]))
        return sc.snapshot_stream(sc.find_store(vol, index=int(where["store_index"])))
    if kind in ("hidden_shadow", "shadow"):
        raw = sc.raw_volume(where["volume"])
        return sc.snapshot_stream(sc.find_store(raw, shadow_id=where["shadow_id"]))
    raise RecoveryError("no volume to read for a %s listing" % kind)
