"""What can be said about an image's integrity before any of it is parsed.

``check_image`` is cheap - it reads section headers, not the media - and runs
for every image:

  stored hashes     the MD5 / SHA-1 an E01 carries in its ``hash`` and
                    ``digest`` sections, written by the acquisition tool
  completeness      whether the last segment is marked final (``done``) and
                    whether the chunks the segments hold cover the media size
                    the image declares. An acquisition stopped part-way can
                    still end in ``done``: the image opens, the first gigabytes
                    parse, and everything past them reads as nothing.
  the files         every segment's path, size and times, so the record says
                    which bytes were examined

``recompute_ewf_hashes`` reads the whole media stream and compares it with the
stored hashes. That is hours for a large disk, so it is never run implicitly.

dissect.evidence parses the sections but does not decode ``hash`` /
``digest``; their layout is fixed by the EWF format (libewf documentation):
hash = MD5[16] + unknown[16] + checksum; digest = MD5[16] + SHA-1[20] + pad.
"""
import hashlib
import os

try:
    from utils.custody import file_times
except Exception:                                   # standalone use
    def file_times(path):
        try:
            st = os.stat(path)
            return {"size": st.st_size}
        except OSError as e:
            return {"error": str(e)}

EWF_EXTENSIONS = (".e01", ".ex01", ".s01", ".l01", ".lx01")


def _is_ewf(path):
    return os.path.splitext(path)[1].lower() in EWF_EXTENSIONS


def _hex_or_none(raw):
    if not raw or not raw.strip(b"\x00"):
        return None                     # an all-zero field means "not recorded"
    return raw.hex()


def check_ewf(first_segment):
    """Integrity facts for an EWF image. Never raises; problems are listed."""
    out = {"format": "EWF", "segments": [], "stored_hashes": {}, "complete": None,
           "declared_bytes": None, "covered_bytes": None, "coverage": None,
           "problems": []}
    try:
        from dissect.evidence.ewf import EWF, find_files
    except Exception as e:
        out["problems"].append("dissect.evidence is not available: %s" % e)
        return out
    handles = []
    try:
        paths = [str(p) for p in find_files(first_segment)] or [first_segment]
        for p in paths:
            entry = {"path": p}
            entry.update(file_times(p))
            out["segments"].append(entry)
        handles = [open(p, "rb") for p in paths]
        ewf = EWF(handles)
        chunk = ewf.chunk_size
        declared_chunks = ewf.volume.chunk_count
        segments = list(getattr(ewf, "_segments", {}).values())
        covered_chunks = sum(getattr(s, "chunk_count", 0) or 0 for s in segments)
        out["declared_bytes"] = ewf.size
        out["covered_bytes"] = min(covered_chunks * chunk, ewf.size)
        out["coverage"] = round(out["covered_bytes"] / float(ewf.size), 6) if ewf.size else None
        final = False
        for seg in segments:
            for section in seg.sections:
                kind = section.type.rstrip(b"\x00")
                if kind == b"done":
                    final = True
                elif kind in (b"hash", b"digest"):
                    seg.fh.seek(section.data_offset)
                    data = seg.fh.read(36)
                    md5 = _hex_or_none(data[:16])
                    if md5:
                        out["stored_hashes"]["md5"] = md5
                    if kind == b"digest":
                        sha1 = _hex_or_none(data[16:36])
                        if sha1:
                            out["stored_hashes"]["sha1"] = sha1
        out["complete"] = bool(final and covered_chunks >= declared_chunks)
        if not final:
            out["problems"].append("missing_segments")
        elif covered_chunks < declared_chunks:
            out["problems"].append("image_incomplete")
        if not out["stored_hashes"]:
            out["problems"].append("image_no_stored_hash")
    except Exception as e:
        out["problems"].append("could not read the image structure: %s" % e)
    finally:
        for fh in handles:
            try:
                fh.close()
            except Exception:
                pass
    return out


def check_image(paths):
    """Integrity facts for any image; only EWF carries stored hashes."""
    paths = [p for p in (paths or []) if p]
    if not paths:
        return {"format": None, "segments": [], "problems": ["no image given"]}
    if _is_ewf(paths[0]):
        return check_ewf(paths[0])
    out = {"format": os.path.splitext(paths[0])[1].lstrip(".").upper() or "RAW",
           "segments": [], "stored_hashes": {}, "complete": None, "problems": []}
    for p in paths:
        entry = {"path": p}
        entry.update(file_times(p))
        out["segments"].append(entry)
    return out


def recompute_ewf_hashes(first_segment, progress=None, block=8 * 1024 * 1024):
    """Read the whole media stream: MD5 + SHA-1, compared with the stored ones.

    ``progress(done_bytes, total_bytes)`` is called per block and may return
    True to stop. Hours for a large disk - only on request.
    """
    from dissect.evidence.ewf import EWF, find_files
    facts = check_ewf(first_segment)
    paths = [str(p) for p in find_files(first_segment)] or [first_segment]
    handles = [open(p, "rb") for p in paths]
    md5, sha1, done = hashlib.md5(), hashlib.sha1(), 0
    try:
        ewf = EWF(handles)
        stream = ewf.open()
        total = ewf.size
        while done < total:
            data = stream.read(min(block, total - done))
            if not data:
                break
            md5.update(data)
            sha1.update(data)
            done += len(data)
            if progress and progress(done, total):
                return {"stopped": True, "read_bytes": done}
    finally:
        for fh in handles:
            fh.close()
    got = {"md5": md5.hexdigest(), "sha1": sha1.hexdigest()}
    stored = facts.get("stored_hashes", {})
    return {
        "read_bytes": done,
        "computed": got,
        "stored": stored,
        "matches": {k: got[k] == v for k, v in stored.items()} or None,
    }
