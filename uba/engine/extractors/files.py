"""
File & directory activity from the NTFS USN journal (with $MFT path
reconstruction), serving five rules at once: created / deleted (hard) /
soft-deleted (Recycle Bin) / renamed / edited.

Approach (single pass over ~200k rows):
1. Stream journal_events ordered by (timestamp, usn), classify each row.
2. Resolve paths through a bulk frn -> reconstructed_path map built from
   mft_usn_correlated (when that DB exists).
3. RENAME halves are paired by (volume, frn); a rename whose new name is a
   $R/$I entry (or lands in $Recycle.Bin) is the Explorer soft delete.
4. Everything else is burst-aggregated (folder bucket + 300s gap) so
   managers see "312 files were created in the Downloads folder within
   4 minutes", not 312 rows.

Attribution: the journal records no user. A burst is attributed only when
its files live inside a known profile's own folder tree (C:\\Users\\<name>\\...)
— otherwise the actor stays EMPTY. Windows-system-area bursts become System.
If the Recycle Bin path carries a SID folder, that SID is resolved.
"""

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional

from uba.engine import aggregation, description
from uba.engine.models import (BehaviorEvent, EvidenceRef, CONF_ARTIFACT_ONLY,
                               CONF_INFERENCE, SEV_SUSPICIOUS, SEV_NOTABLE)
from uba.utils.timeparse import normalize_ts

logger = logging.getLogger(__name__)

MAX_PATH_MAP_ENTRIES = 600_000
MASS_OP_THRESHOLD = 100          # burst size that escalates severity
INDIVIDUAL_RENAME_MAX = 20       # per-folder renames shown individually (names visible)
# Extensions that, when a rename lands on them, hint at packaging/encryption.
_ARCHIVE_ENC_EXTS = {"zip", "rar", "7z", "gz", "tar", "cab", "iso",
                     "enc", "locked", "crypt", "crypted", "encrypted"}
# NTFS File Reference Numbers pack a 16-bit sequence number in the high bits;
# the low 48 bits are the $MFT record number the correlated table is keyed on.
_FRN_RECORD_MASK = 0x0000FFFFFFFFFFFF
_SID_IN_PATH_RE = re.compile(r"\$recycle\.bin[\\/](S-1-5-21-[\d-]+)", re.I)
_USER_DIR_RE = re.compile(r"[\\/]users[\\/]([^\\/]+)[\\/]", re.I)
# Reconstructed paths use forward slashes, 8.3 short names and no drive
# letter (e.g. './Windows/SystemTemp/...'), so system-area detection is done
# here with slash-agnostic markers rather than attribution.from_path.
_SYSTEM_AREA_RE = re.compile(
    r"[\\/](windows|program files|program files \(x86\)|programdata)[\\/]", re.I)


def _mft_record(frn) -> Optional[int]:
    """USN FRN (stored as a string) -> $MFT record number, or None."""
    if frn in (None, "", "0"):
        return None
    try:
        return int(frn) & _FRN_RECORD_MASK
    except (TypeError, ValueError):
        return None

_OP_RULE_KEY = {
    aggregation.OP_CREATE: "file_created",
    aggregation.OP_DELETE: "file_deleted",
    aggregation.OP_MODIFY: "file_edited",
    aggregation.OP_RENAME: "file_renamed",
    aggregation.OP_SOFT_DELETE: "file_soft_deleted",
}

_OP_PHRASES = {
    aggregation.OP_CREATE: ("was created", "were created"),
    aggregation.OP_DELETE: ("was permanently deleted (bypassing the Recycle Bin)",
                            "were permanently deleted (bypassing the Recycle Bin)"),
    aggregation.OP_MODIFY: ("was changed", "were changed"),
    aggregation.OP_RENAME: ("was renamed or moved", "were renamed or moved"),
}


def _build_path_map(ctx) -> Dict[int, str]:
    """frn -> reconstructed path, bulk-loaded once."""
    path_map: Dict[int, str] = {}
    conn = ctx.pool.get("mft_usn_correlated")
    if conn is None or not ctx.pool.has_table("mft_usn_correlated", "mft_usn_correlated"):
        return path_map
    try:
        cursor = conn.execute(
            "SELECT mft_record_number, reconstructed_path FROM mft_usn_correlated "
            "WHERE reconstructed_path IS NOT NULL")
        for frn, path in cursor:
            if frn is None:
                continue
            path_map[frn] = path
            if len(path_map) >= MAX_PATH_MAP_ENTRIES:
                logger.warning("UBA: path map capped at %d entries", MAX_PATH_MAP_ENTRIES)
                break
    except Exception as e:
        logger.warning("UBA: path map build failed: %s", e)
    logger.info("UBA: path map holds %d paths", len(path_map))
    return path_map


def _actor_for_path(ctx, path: Optional[str]):
    """Attribution from file location only when it is unambiguous."""
    if not path:
        return ("", "", "")
    match = _USER_DIR_RE.search(str(path))
    if match:
        dirname = match.group(1)
        for username in ctx.resolver.known_users.values():
            if dirname.lower() == username.lower():
                return ("User", username,
                        "the files are inside {}'s own user folder".format(username))
        return ("", "", "")
    if _SYSTEM_AREA_RE.search(str(path)):
        return ("System", "Windows",
                "the files are inside the Windows / installed-programs system area")
    return ("", "", "")


def _burst_actor(ctx, burst: aggregation.Burst):
    """A burst gets an actor only if ALL sampled paths agree."""
    actors = set()
    for row in burst.rows[:200]:
        actors.add(_actor_for_path(ctx, row.path or row.filename)[:2])
        if len(actors) > 1:
            return ("", "", "")
    if len(actors) == 1:
        sample = burst.rows[0]
        return _actor_for_path(ctx, sample.path or sample.filename)
    return ("", "", "")


def usn_file_activity(ctx, rules) -> List[BehaviorEvent]:
    rules_by_key = {r["id"]: r for r in rules}
    conn = ctx.pool.get("usn")
    if conn is None or not ctx.pool.has_table("usn", "journal_events"):
        return _recyclebin_db_events(ctx, rules_by_key)

    path_map = _build_path_map(ctx)
    op_rows = defaultdict(list)
    rename_rows: List[aggregation.UsnRow] = []
    skipped = 0

    try:
        cursor = conn.execute(
            "SELECT rowid, volume_letter, filename, usn, frn, parent_frn, "
            "timestamp, reason FROM journal_events ORDER BY timestamp, usn")
    except Exception as e:
        logger.warning("UBA: USN stream failed: %s", e)
        return _recyclebin_db_events(ctx, rules_by_key)

    for rowid, volume, filename, usn, frn, parent_frn, ts, reason in cursor:
        op = aggregation.classify_reason(reason)
        if op is None:
            skipped += 1
            continue
        ts_norm = normalize_ts(ts)
        if not ts_norm:
            skipped += 1
            continue
        # Prefer the file's own reconstructed path; fall back to its folder.
        own = _mft_record(frn)
        parent = _mft_record(parent_frn)
        path = (path_map.get(own) if own is not None else None) or \
               (path_map.get(parent) if parent is not None else None)
        row = aggregation.usn_row_from_db(rowid, volume, filename, usn, frn,
                                          parent_frn, ts_norm, reason, path)
        if row is None:
            skipped += 1
            continue
        if op == aggregation.OP_RENAME:
            rename_rows.append(row)
        else:
            op_rows[op].append(row)
    ctx.bump("usn_rows_skipped_noise", skipped)

    events: List[BehaviorEvent] = []
    aggregator = aggregation.BurstAggregator()

    # --- renames: pair halves, split soft deletes out ------------------- #
    # Recycle-Bin moves (rename into $Recycle.Bin) -> soft delete (get the
    # original name by pairing OLD -> $R).
    pairs = aggregation.pair_renames(rename_rows)
    soft_delete_rule = rules_by_key.get("file_soft_deleted")
    for pair in pairs:
        anchor = pair.anchor
        if anchor is None or not pair.is_recycle_move() or soft_delete_rule is None:
            continue
        original = pair.old.filename if pair.old else None
        evidence_ids = [r.rowid for r in (pair.old, pair.new) if r]
        actor = ("", "", "")
        for row in (pair.new, pair.old):
            if row and row.path:
                sid_match = _SID_IN_PATH_RE.search(row.path)
                if sid_match:
                    actor = ctx.resolver.from_sid(
                        sid_match.group(1), "the Recycle Bin folder owner")
                    break
        if not actor[0] and original:
            actor = _actor_for_path(ctx, pair.old.path or original)
        name_part = ("'{}'".format(original) if original
                     else "a file (previous name not recorded)")
        events.append(BehaviorEvent(
            rule_id=soft_delete_rule["id"],
            behavior_class=soft_delete_rule["behavior_class"],
            activity=soft_delete_rule["activity"],
            ts_start=anchor.ts, ts_end=anchor.ts,
            actor_type=actor[0], actor_name=actor[1], actor_basis=actor[2],
            description="{} deleted {} to the Recycle Bin".format(
                actor[1] or "Someone", name_part),
            severity=soft_delete_rule["severity"],
            confidence=CONF_ARTIFACT_ONLY,
            session_context=ctx.session_context(anchor.ts),
            details={"original_name": original},
            evidence=[EvidenceRef(db="usn", table="journal_events",
                                  rowids=evidence_ids, count=len(evidence_ids))]))

    # Actual renames -> per-file name-history chains ($R rows excluded).
    rename_rule = rules_by_key.get("file_renamed")
    if rename_rule is not None:
        chains, _ = aggregation.build_rename_chains(rename_rows)
        # group by (volume, folder area, actor); small groups -> per-file
        # events (names visible), large groups -> one burst.
        groups = defaultdict(list)
        for ch in chains:
            actor = _actor_for_path(ctx, ch.path)
            bucket = description.folder_label(ch.path or (ch.names[-1] if ch.names else None))
            groups[(ch.volume, bucket, actor[:2])].append((ch, actor))
        for (volume, bucket, _a), items in groups.items():
            if len(items) <= INDIVIDUAL_RENAME_MAX:
                for ch, actor in items:
                    events.append(_rename_chain_event(ctx, rename_rule, ch, actor, bucket))
            else:
                events.append(_rename_burst_event(ctx, rename_rule, items, bucket))

    # --- create / delete / modify bursts -------------------------------- #
    for op, rows in op_rows.items():
        for burst in aggregator.aggregate(iter(rows), op):
            events.append(_burst_event(ctx, rules_by_key, burst))

    events = [e for e in events if e is not None]
    events.extend(_recyclebin_db_events(ctx, rules_by_key))
    return events


def _burst_event(ctx, rules_by_key, burst: aggregation.Burst):
    rule = rules_by_key.get(_OP_RULE_KEY[burst.op])
    if rule is None:
        return None
    n = len(burst.rows)
    singular, plural = _OP_PHRASES[burst.op]
    actor = _burst_actor(ctx, burst)
    samples = burst.sample_names()

    if n == 1:
        name = samples[0] if samples else "A file"
        text = "'{}' {} in {}".format(name, singular, burst.folder_bucket)
    else:
        text = "{} files {} in {}".format(n, plural, burst.folder_bucket)
        span = description.span_phrase(burst.ts_start, burst.ts_end)
        if span:
            text += " " + span
    if actor[0] == "User":
        text = "{}: {}".format(actor[1], text)

    severity = rule["severity"]
    if n >= MASS_OP_THRESHOLD and burst.op in (aggregation.OP_DELETE,
                                               aggregation.OP_RENAME):
        severity = SEV_SUSPICIOUS
        text += " — unusually large number of files at once"
    elif n >= MASS_OP_THRESHOLD * 10 and burst.op == aggregation.OP_MODIFY:
        severity = SEV_NOTABLE

    # Store the burst's exact rowids (bounded by MAX_BURST_ROWS) so the
    # evidence modal shows precisely these records — a rowid BETWEEN range
    # would wrongly include interleaved rows from other folders/bursts.
    return BehaviorEvent(
        rule_id=rule["id"], behavior_class=rule["behavior_class"],
        activity=rule["activity"], ts_start=burst.ts_start, ts_end=burst.ts_end,
        actor_type=actor[0], actor_name=actor[1], actor_basis=actor[2],
        description=text, severity=severity, confidence=CONF_ARTIFACT_ONLY,
        session_context=ctx.session_context(burst.ts_start),
        aggregate_count=n,
        details={"folder": burst.folder_bucket, "operation": burst.op,
                 "sample_files": samples,
                 "file_types": burst.extension_histogram()},
        evidence=[EvidenceRef(db="usn", table="journal_events",
                              rowids=[r.rowid for r in burst.rows], count=n)])


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if name and "." in name else ""


def _rename_chain_event(ctx, rule, chain, actor, bucket):
    """One event for a single file's rename history (names visible)."""
    names = chain.names
    old, new = names[0], names[-1]
    times = len(names) - 1
    if times <= 1:
        text = "'{}' was renamed to '{}'".format(old, new)
    else:
        text = "'{}' was renamed to '{}' (renamed {} times)".format(old, new, times)
    if actor[0] == "User":
        text = "{}: {}".format(actor[1], text)

    severity = rule["severity"]
    if _ext(new) in _ARCHIVE_ENC_EXTS and _ext(new) != _ext(old):
        severity = SEV_SUSPICIOUS
        text += " — renamed into an archive/encrypted-looking extension"

    rowids = [r.rowid for r in chain.rows]
    return BehaviorEvent(
        rule_id=rule["id"], behavior_class=rule["behavior_class"],
        activity=rule["activity"], ts_start=chain.ts_start, ts_end=chain.ts_end,
        actor_type=actor[0], actor_name=actor[1], actor_basis=actor[2],
        description=text, severity=severity, confidence=CONF_ARTIFACT_ONLY,
        session_context=ctx.session_context(chain.ts_start),
        aggregate_count=times,
        details={"folder": bucket, "operation": "renamed", "rename_chain": names},
        evidence=[EvidenceRef(db="usn", table="journal_events",
                              rowids=rowids, count=len(rowids))])


def _rename_burst_event(ctx, rule, items, bucket):
    """One event summarizing many renames in a folder (sample chains kept)."""
    chains = [ch for ch, _a in items]
    n = len(chains)
    # actor only if all agree
    actors = {a[:2] for _ch, a in items}
    actor = items[0][1] if len(actors) == 1 else ("", "", "")
    ts_start = min(c.ts_start for c in chains)
    ts_end = max(c.ts_end for c in chains)
    text = "{} files were renamed in {}".format(n, bucket)
    span = description.span_phrase(ts_start, ts_end)
    if span:
        text += " " + span
    if actor[0] == "User":
        text = "{}: {}".format(actor[1], text)
    severity = rule["severity"]
    if n >= MASS_OP_THRESHOLD:
        severity = SEV_SUSPICIOUS
        text += " — unusually large number of files at once"
    rowids = [r.rowid for c in chains for r in c.rows]
    return BehaviorEvent(
        rule_id=rule["id"], behavior_class=rule["behavior_class"],
        activity=rule["activity"], ts_start=ts_start, ts_end=ts_end,
        actor_type=actor[0], actor_name=actor[1], actor_basis=actor[2],
        description=text, severity=severity, confidence=CONF_ARTIFACT_ONLY,
        session_context=ctx.session_context(ts_start), aggregate_count=n,
        details={"folder": bucket, "operation": "renamed",
                 "sample_chains": [c.names for c in chains[:8]]},
        evidence=[EvidenceRef(db="usn", table="journal_events",
                              rowids=rowids[:5000], count=len(rowids))])


def _recyclebin_db_events(ctx, rules_by_key) -> List[BehaviorEvent]:
    """Primary soft-delete source when recyclebin_analysis.db exists.
    Column names differ across parser versions, so they are detected."""
    rule = rules_by_key.get("file_soft_deleted")
    if rule is None or not ctx.pool.has_table("recyclebin", "recycle_bin_entries"):
        return []
    from uba.utils.db_access import table_columns
    conn = ctx.pool.get("recyclebin")
    cols = {c.lower(): c for c in table_columns(conn, "recycle_bin_entries")}

    def pick(*names):
        for name in names:
            if name in cols:
                return cols[name]
        return None

    name_col = pick("original_filename", "original_path", "original_name",
                    "file_name", "filename")
    time_col = pick("deleted_time", "deletion_time", "deleted_timestamp",
                    "deletion_date")
    sid_col = pick("user_sid", "sid")
    if not name_col:
        return []
    select = ["rowid", name_col]
    select.append(time_col if time_col else "NULL")
    select.append(sid_col if sid_col else "NULL")
    events = []
    try:
        rows = conn.execute("SELECT {} FROM recycle_bin_entries".format(
            ", ".join(select))).fetchall()
    except Exception as e:
        logger.warning("UBA: recycle bin query failed: %s", e)
        return []
    for rowid, name, deleted_time, sid in rows:
        ts = normalize_ts(deleted_time)
        actor = ctx.resolver.from_sid(sid, "the Recycle Bin entry owner") if sid \
            else _actor_for_path(ctx, name)
        events.append(BehaviorEvent(
            rule_id=rule["id"], behavior_class=rule["behavior_class"],
            activity=rule["activity"], ts_start=ts, ts_end=ts,
            actor_type=actor[0], actor_name=actor[1], actor_basis=actor[2],
            description="{} deleted '{}' to the Recycle Bin".format(
                actor[1] or "Someone", name),
            severity=rule["severity"], confidence=CONF_ARTIFACT_ONLY,
            session_context=ctx.session_context(ts) if ts else "",
            details={"original_path": name},
            evidence=[EvidenceRef(db="recyclebin", table="recycle_bin_entries",
                                  rowids=[rowid], count=1)]))
    return events


_COPY_CAVEAT = (
    "This is a heuristic: a file whose contents are older than the moment it "
    "appeared on this disk is typically a copy, but the same pattern can occur "
    "from restores, syncs or extraction from an archive.")


def file_copy_inferred(ctx, rules) -> List[BehaviorEvent]:
    """Inferred file copies into a user's own folders.

    Signature: `si_creation_time > si_modification_time` — the file was
    created on this volume *after* its own contents were last modified, the
    classic copy tell. Restricted to user document areas (Desktop / Documents /
    Downloads / …): the raw signature is dominated by Windows WinSxS servicing
    of system files, which is not user activity and is excluded. Confidence is
    'inference' and the wording never asserts certainty.
    """
    rule = rules[0]
    conn = ctx.pool.get("mft_usn_correlated")
    if conn is None or not ctx.pool.has_table("mft_usn_correlated",
                                              "mft_usn_correlated"):
        return []
    from collections import defaultdict
    buckets = defaultdict(lambda: {"rowids": [], "names": [], "first_ts": None,
                                   "actor": ("", "", "")})
    try:
        cursor = conn.execute(
            "SELECT rowid, fn_filename, reconstructed_path, si_creation_time, "
            "si_modification_time FROM mft_usn_correlated "
            "WHERE si_modification_time IS NOT NULL AND si_modification_time != '' "
            "AND si_creation_time > si_modification_time")
    except Exception as e:
        logger.warning("UBA: copy-inference query failed: %s", e)
        return []

    for rowid, fname, path, created, modified in cursor:
        if not description.is_user_document_area(path):
            continue                       # exclude system/servicing noise
        ts = normalize_ts(created)
        if not ts:
            continue
        actor = _actor_for_path(ctx, path)
        key = (description.folder_label(path), ts[:10])
        b = buckets[key]
        b["rowids"].append(rowid)
        if fname and len(b["names"]) < 10:
            b["names"].append(fname)
        if b["first_ts"] is None or ts < b["first_ts"]:
            b["first_ts"] = ts
        if not b["actor"][0] and actor[0]:
            b["actor"] = actor

    events = []
    for (folder, day), b in buckets.items():
        n = len(b["rowids"])
        actor = b["actor"]
        who = "{}: ".format(actor[1]) if actor[0] == "User" else ""
        if n == 1:
            text = "{}A file ('{}') appears to have been copied into {}".format(
                who, b["names"][0] if b["names"] else "a file", folder)
        else:
            text = "{}{} files appear to have been copied into {}".format(
                who, n, folder)
        events.append(BehaviorEvent(
            rule_id=rule["id"], behavior_class=rule["behavior_class"],
            activity=rule["activity"], ts_start=b["first_ts"], ts_end=b["first_ts"],
            actor_type=actor[0], actor_name=actor[1], actor_basis=actor[2],
            description=text, severity=rule["severity"],
            confidence=CONF_INFERENCE, caveat=_COPY_CAVEAT,
            session_context=ctx.session_context(b["first_ts"]),
            aggregate_count=n,
            details={"folder": folder, "sample_files": b["names"]},
            evidence=[EvidenceRef(db="mft_usn_correlated",
                                  table="mft_usn_correlated",
                                  rowids=b["rowids"][:50], count=n)]))
    return events
