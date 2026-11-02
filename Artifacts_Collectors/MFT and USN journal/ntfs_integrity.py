"""NTFS integrity checks, and the delta MFT parse they ride on.

Two halves:

1. **The rules**, as pure functions over one record's facts (its header and
   what ntfs_digest_map.walk() read from its attributes) or over one volume's
   facts. No I/O, no settings: Sentinel calls the same functions.
2. **IntegrityRun**, which drives them over one parse of one volume: it reads
   the settings, loads the previous digest map, decides between a full parse
   and a delta parse (and says why), digests every record the parser reads,
   tells the parser which records to parse, runs the checks, writes the
   findings and the new map, and writes the volume's integrity manifest to the
   case's chain-of-custody ledger.

The checks built here are the ones a single image can answer (P1). The ones
that need the previous parse's map - SEMANTIC changed with an unchanged LSN
(D2), times moving backwards (D8), wiped records with a tombstone (D9 with
history), USN and $LogFile continuity between parses (D4/D5 with history) -
and the P2 checks come in later steps; the map they need is written now.

| ID  | Check | Setting (one per group) |
|-----|-------|-------------------------|
| D1  | what changed between parses: deletions, reuse | ntfs_integrity_digest_map |
| D3  | a record LSN above the highest LSN in $LogFile | ntfs_integrity_lsn_checks |
| D4  | the USN journal's state (ID, range, deleted, disabled) | ntfs_integrity_usn_continuity |
| D5  | $LogFile restart pages: clean flag, version, agreement | ntfs_integrity_logfile_continuity |
| D7  | SI vs FN times (two comparisons, nothing more) | ntfs_integrity_timestomp |
| D9  | an in-use record wiped or emptied | ntfs_integrity_wipe_detect |
| D10 | fixups, BAAD, bytes in use, link count | ntfs_integrity_structural |
| D29 | $MFT:$BITMAP against each record's in-use flag | ntfs_integrity_structural |

Every check is on by default and can be turned off in Settings -> Parsing ->
NTFS integrity checks. A check that is off is written to custody at every
parse, so a silenced check never reads as a clean result. The delta parse
(``mft_delta_parse``) is a separate switch: turning the checks off does not
silently change how the MFT is parsed.
"""

import datetime
import hashlib
import json
import logging
import os
import struct
import time
import uuid
from collections import Counter, OrderedDict, namedtuple

try:
    import ntfs_digest_map as dm
except ImportError:                                          # imported as a package
    from . import ntfs_digest_map as dm                      # noqa: F401

logger = logging.getLogger(__name__)

PARSER_VERSION = "MFT_Claw 2.0.0; digest map %d; semantic 1" % dm.FORMAT_VERSION
MANIFEST_FORMAT = "crow-eye-ntfs-integrity/1"

# ------------------------------------------------------------------ settings --
# The same keys in Crow-Eye (GlobalConfig) and in Sentinel's signed policy.
SETTING_DEFAULTS = OrderedDict([
    ('ntfs_integrity_enabled', True),            # the master switch
    ('mft_delta_parse', True),                   # separate from the master
    ('ntfs_integrity_digest_map', True),         # D1
    ('ntfs_integrity_lsn_checks', True),         # D2 / D3
    ('ntfs_integrity_usn_continuity', True),     # D4
    ('ntfs_integrity_logfile_continuity', True),  # D5
    ('ntfs_integrity_offline_detect', True),     # D6 (Sentinel)
    ('ntfs_integrity_timestomp', True),          # D7 / D8 / D21 / D24 / D27
    ('ntfs_integrity_wipe_detect', True),        # D9 / D17
    ('ntfs_integrity_structural', True),         # D10 / D12 / D13 / D29
    ('ntfs_integrity_usn_witness', True),        # D11
    ('ntfs_integrity_ads_ea_reparse', True),     # D14 - D16
    ('ntfs_integrity_clock', True),              # D18
    ('ntfs_integrity_vss_inventory', True),      # D19
    ('ntfs_integrity_security_links', True),     # D20
    ('ntfs_integrity_i30', True),                # D22
    ('ntfs_integrity_logfile_deep', True),       # D23
    ('ntfs_integrity_txf_efs', True),            # D25 / D26
    ('ntfs_integrity_timestamp_stego', False),   # D28 - off by default
    ('ntfs_integrity_weekly_full_parse', True),  # Sentinel only
    # D11 is an annotation until it is tuned in the lab; 'alert' later.
    ('ntfs_integrity_usn_witness_mode', 'annotation'),
])

# The check groups this version runs, with the rules each one covers and the
# label the Settings page shows. The rest of SETTING_DEFAULTS are stored and
# honoured by name, and listed in every manifest as "not built in this
# version" - their absence must not read as a clean result.
BUILT_CHECKS = OrderedDict([
    ('ntfs_integrity_digest_map', ('D1', "Record what changed between parses (deletions, reused records)")),
    ('ntfs_integrity_lsn_checks', ('D3', "A record LSN above the highest LSN in $LogFile")),
    ('ntfs_integrity_usn_continuity', ('D4', "USN journal state: deleted, being deleted, or not active")),
    ('ntfs_integrity_logfile_continuity', ('D5', "$LogFile restart pages: empty log, copies that disagree")),
    ('ntfs_integrity_timestomp', ('D7', "Timestomping: $STANDARD_INFORMATION earlier than $FILE_NAME")),
    ('ntfs_integrity_wipe_detect', ('D9', "An in-use record wiped or emptied")),
    ('ntfs_integrity_structural', ('D10, D29', "Record structure (fixups, BAAD, sizes, link count) and the $MFT bitmap")),
])


def read_settings(reader=None):
    """Every key, from Settings (global_config.json) through
    read_global_setting - never <source>/config/global_config.json."""
    if reader is None:
        try:
            from config.case_history_manager import read_global_setting as reader
        except Exception:                                    # noqa: BLE001
            reader = None
    out = OrderedDict()
    for key, default in SETTING_DEFAULTS.items():
        value = default
        if reader is not None:
            try:
                value = reader(key, default)
            except Exception:                                # noqa: BLE001
                value = default
        out[key] = value if value is not None else default
    return out


def policy_hash(settings):
    body = json.dumps({k: settings.get(k) for k in SETTING_DEFAULTS}, sort_keys=True)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


# -------------------------------------------------------------- the findings --
SEVERITIES = ('high', 'medium', 'low', 'info')
MAX_PER_CHECK = 1000          # per volume per parse; the rest are counted
FIRST_RECORD_CHECKED = 24     # 0-15 are NTFS metadata files, 16-23 reserved

# FILETIME of 1980-01-01: a time before it is not a time a file was given by
# NTFS, and is left out of the comparisons (zero means "never set").
FT_1980 = 119600064000000000


def finding(rule, check, group, severity, detail, record=None, seq=None, lsn=None,
            name=None, evidence=None):
    return {'rule': rule, 'check': check, 'group': group, 'severity': severity,
            'detail': detail, 'record_number': record, 'sequence_number': seq,
            'lsn': lsn, 'file_name': name, 'evidence': evidence or {}}


def finding_id(f, volume_key):
    """Stable across parses: (rule.check, volume, FRN, sequence, LSN). A
    re-parse that finds the same thing again stores nothing new.

    A rule whose condition is a pair of values rather than a moment (D7: the
    SI and FN times) sets ``id_lsn`` None and puts the values in
    ``_id_extra``: a busy directory gets a new LSN with every change, and the
    same unchanged times must not become a new row on every delta parse."""
    lsn = f['id_lsn'] if 'id_lsn' in f else f.get('lsn')
    parts = ['%s.%s' % (f['rule'], f['check']), volume_key,
             '-' if f.get('record_number') is None else str(f['record_number']),
             '-' if f.get('sequence_number') is None else str(f['sequence_number']),
             '-' if lsn is None else '%x' % lsn]
    key = f.get('evidence', {}).get('_id_extra')
    if key is not None:
        parts.append(str(key))
    return '|'.join(parts)


def ft_text(ticks):
    """A FILETIME with all seven sub-second digits, UTC. The tables keep
    whole seconds; a timestomp is judged on the ticks, so it is shown in them."""
    if not ticks:
        return None
    try:
        from utils.time_utils import filetime_to_datetime
        dt = filetime_to_datetime(int(ticks))
        if dt is None:
            return None
        return '%s.%07d' % (dt.strftime('%Y-%m-%d %H:%M:%S'), int(ticks) % 10000000)
    except Exception:                                        # noqa: BLE001
        return None


def _primary_name(fns):
    for fn in fns or []:
        if fn.get('namespace') != 2:
            return fn.get('name')
    return (fns[0].get('name') if fns else None)


# ------------------------------------------------------------ D7 timestomp --
TimestompRule = namedtuple('TimestompRule', 'check si_field op fn_field emitted severity text')

# The comparisons, kept in one place for the parse, the MFT/USN correlator's
# partial index and the MFT/USN dashboard. All four times compared would flood:
# copies, extraction and robocopy leave SI modified older than FN as a matter
# of course, and FN times change only on create, rename or move.
#
# Severities are from the first live read (C: of the build host, 200,000
# records, 2026-10-26), not from the plan's "H": SI created < FN created held
# for 40% of the records - every file deployed from the Windows image keeps the
# image's SI times while its FN times are the install date - so on its own it
# is a low-weight candidate, and a volume where it is common gets one volume
# row instead of a thousand (see IntegrityRun._COLLAPSE). SI MFT-changed < FN
# created held for 0.8%, ETW logs and rotated application logs among them:
# medium until D21 (tunneling) and D24 (zero sub-seconds) can separate them.
#
# 2026-11-01, the same C: - of 47,864 records with MFT-changed < FN created,
# 42,012 had SI created EQUAL to FN created - installers, pip and archive
# extraction set an older changed time on files they create, the creation was
# never moved back. rule_timestomp now asks for SI created < FN created as
# well (5,851 records: an OEM image applied in one sitting, and source trees
# brought over with their times kept). The shared timestomp_hits is
# unchanged; the correlator's SQL form keeps its own meaning.
TIMESTOMP_RULES = (
    TimestompRule('si_created_before_fn_created', 'created', '<', 'created', True, 'low',
                  "$STANDARD_INFORMATION created is earlier than $FILE_NAME created"),
    TimestompRule('si_mft_changed_before_fn_created', 'mft_modified', '<', 'created', True, 'medium',
                  "$STANDARD_INFORMATION created and MFT-entry-changed are both earlier than "
                  "$FILE_NAME created"),
    # Forward-dating: the MFT/USN dashboard's "timestomp candidates". Not
    # emitted by the parse (whole-second columns, and installers do it).
    TimestompRule('si_created_after_fn_created', 'created', '>', 'created', False, 'low',
                  "Standard-Info creation is newer than File-Name creation (possible forward-dating)"),
)

# Column names in the MFT/USN correlator's table, for the SQL form.
_CORR_COLUMNS = {'si': {'created': 'si_creation_time', 'mft_modified': 'si_mft_entry_change_time'},
                 'fn': {'created': 'fn_creation_time'}}


def timestomp_rule(check):
    for r in TIMESTOMP_RULES:
        if r.check == check:
            return r
    raise KeyError(check)


def timestomp_sql(check):
    """The comparison as SQL over mft_usn_correlated, e.g.
    'si_creation_time > fn_creation_time' - the text of the correlator's
    partial index idx_corr_timestomp, which a query must repeat to use it."""
    r = timestomp_rule(check)
    return '%s %s %s' % (_CORR_COLUMNS['si'][r.si_field], r.op, _CORR_COLUMNS['fn'][r.fn_field])


def timestomp_hits(si_created, si_mft_modified, fn_created, floor=None, emitted_only=False):
    """The rules that fire for one file. Values are ticks or same-format text;
    ``floor`` leaves out values before it (unset or implausible times)."""
    vals = {'created': si_created, 'mft_modified': si_mft_modified}
    hits = []
    for r in TIMESTOMP_RULES:
        if emitted_only and not r.emitted:
            continue
        a = vals.get(r.si_field)
        b = fn_created
        if not a or not b:
            continue
        if floor is not None and (a < floor or b < floor):
            continue
        if (a < b) if r.op == '<' else (a > b):
            hits.append(r)
    return hits


def rule_timestomp(rn, header, facts, now_ticks=None):
    """D7 on one record. The earliest $FILE_NAME created is the reference: a
    hard link's later name has a later FN created, and comparing against it
    would flag every System32 file linked from WinSxS."""
    si = facts.get('si')
    fns = [fn for fn in facts.get('fns') or [] if fn.get('namespace') != 2 and fn.get('created')]
    if not si or not fns or header.get('base_record') or rn < FIRST_RECORD_CHECKED:
        return []
    fn_created = min(fn['created'] for fn in fns)
    upper = now_ticks or (FT_1980 * 10)
    if fn_created < FT_1980 or fn_created > upper:
        return []
    out = []
    names = len({(fn.get('parent_ref'), fn.get('name')) for fn in fns})
    si_created = si.get('created')
    for r in timestomp_hits(si_created, si.get('mft_modified'), fn_created,
                            floor=FT_1980, emitted_only=True):
        # An older entry-changed time on its own is the writer setting times
        # on a file it created (SI created = FN created): only with the
        # creation moved back too is it this finding.
        if r.check == 'si_mft_changed_before_fn_created' and not (
                si_created and FT_1980 <= si_created < fn_created):
            continue
        a = si.get(r.si_field)
        sev = r.severity if names == 1 else 'low'
        f = finding('D7', r.check, 'ntfs_integrity_timestomp', sev,
                    r.text + (" (the file has %d names; a removed first name "
                              "can also cause this)" % names if names > 1 else ""),
                    record=rn, seq=header.get('sequence'), lsn=header.get('lsn'),
                    name=_primary_name(facts.get('fns')),
                    evidence={'si_' + r.si_field: a, 'si_' + r.si_field + '_utc': ft_text(a),
                              'fn_created': fn_created, 'fn_created_utc': ft_text(fn_created),
                              'difference_seconds': round((fn_created - a) / 1e7, 7),
                              'names': names, '_id_extra': '%x-%x' % (a, fn_created)})
        f['id_lsn'] = None
        out.append(f)
    return out


# ----------------------------------------------------------------- D9 wipe --
def rule_wiped(rn, header, facts):
    """D9, single image: an in-use base record with nothing in it, or without
    the attributes every file has. NTFS never leaves a record like that."""
    if (not header.get('in_use') or header.get('base_record') or rn < FIRST_RECORD_CHECKED
            or header.get('baad')):
        return []
    types = facts.get('attr_types') or []
    check = None
    if not types:
        check, text = 'in_use_record_has_no_attributes', "An in-use record holds no attributes at all"
    elif 0x10 not in types:
        check, text = ('in_use_record_missing_standard_information',
                       "An in-use record has no $STANDARD_INFORMATION")
    elif 0x30 not in types and not facts.get('has_attribute_list'):
        check, text = ('in_use_record_missing_file_name',
                       "An in-use record has no $FILE_NAME and no attribute list")
    if not check:
        return []
    return [finding('D9', check, 'ntfs_integrity_wipe_detect', 'high', text, record=rn,
                    seq=header.get('sequence'), lsn=header.get('lsn'),
                    name=_primary_name(facts.get('fns')),
                    evidence={'attribute_types': ['0x%X' % t for t in types],
                              'bytes_in_use': header.get('bytes_in_use')})]


# ------------------------------------------------------- D10 structure --
def rule_structure(rn, header, fixup_ok, reread=None, source='live'):
    """D10 on the header: BAAD, an update-sequence mismatch that survived a
    re-read, bytes in use beyond the record's allocation."""
    if not header.get('present'):
        return []
    out = []
    seq, lsn = header.get('sequence'), header.get('lsn')
    if header.get('baad'):
        out.append(finding('D10', 'baad_signature', 'ntfs_integrity_structural', 'high',
                           "The record is marked BAAD (NTFS found it damaged)",
                           record=rn, seq=seq, lsn=lsn))
        return out
    if not fixup_ok:
        if reread is True:
            pass                      # the re-read was clean: a torn live read
        else:
            note = ("still mismatched after one re-read" if reread is False else
                    "a static copy, so it was not re-read; a torn read when the copy was "
                    "taken looks the same")
            out.append(finding('D10', 'fixup_mismatch', 'ntfs_integrity_structural',
                               'high' if reread is False else 'medium',
                               "The update sequence does not match at the end of a stride (%s)" % note,
                               record=rn, seq=seq, lsn=lsn,
                               evidence={'usa_value': header.get('usa_value'), 'source': source}))
    used, alloc = header.get('bytes_in_use') or 0, header.get('bytes_allocated') or 0
    if alloc and used > alloc:
        out.append(finding('D10', 'bytes_in_use_exceeds_allocated', 'ntfs_integrity_structural',
                           'high', "The record says it uses more bytes than it has",
                           record=rn, seq=seq, lsn=lsn,
                           evidence={'bytes_in_use': used, 'bytes_allocated': alloc}))
    return out


def rule_link_count(rn, header, fn_count, name=None):
    """D10: more $FILE_NAME attributes than the header's link count admits.

    Only that direction. The first live read (C:, 3.3 M records) found the
    header count ABOVE the number of $FILE_NAME attributes on 27,462 records -
    WinSxS hard links with POSIX names (4 links, 2 names, both counted across
    the extension records) and TxF directories (3 links for a Win32 + DOS
    pair) - so "not equal" describes ordinary Windows, not tampering. A name
    the count does not account for is what an edit leaves behind. Directories
    are left out. Run once every $FILE_NAME is known (after the extensions)."""
    if (not header.get('in_use') or header.get('base_record') or header.get('directory')
            or rn < FIRST_RECORD_CHECKED):
        return []
    links = header.get('links') or 0
    if fn_count <= links:
        return []
    return [finding('D10', 'link_count_mismatch', 'ntfs_integrity_structural', 'medium',
                    "The record holds %d $FILE_NAME attributes but its header counts only "
                    "%d link(s)" % (fn_count, links),
                    record=rn, seq=header.get('sequence'), lsn=header.get('lsn'), name=name,
                    evidence={'header_link_count': links, 'file_name_attributes': fn_count})]


# ------------------------------------------------------------ D29 bitmap --
def rule_bitmap(rn, allocated, in_use, present, seq=None, lsn=None, wipe_on=True,
                structural_on=True):
    """D29, and D9's zeroed-slot case: the $MFT's own bitmap against the
    record. ``in_use`` is the record's flag, ``present`` whether the slot
    holds a FILE record at all."""
    if rn < FIRST_RECORD_CHECKED:
        return []
    if allocated and not present:
        if wipe_on:
            return [finding('D9', 'allocated_record_zeroed', 'ntfs_integrity_wipe_detect', 'high',
                            "The $MFT bitmap says this record is allocated, but the slot holds "
                            "no FILE record (zeroed or overwritten)", record=rn)]
        return []
    if not structural_on:
        return []
    if allocated and not in_use:
        return [finding('D29', 'bitmap_allocated_record_free', 'ntfs_integrity_structural', 'high',
                        "The $MFT bitmap says this record is allocated, but its in-use flag is clear",
                        record=rn, seq=seq, lsn=lsn)]
    if in_use and not allocated:
        return [finding('D29', 'record_in_use_bitmap_free', 'ntfs_integrity_structural', 'high',
                        "The record is in use, but the $MFT bitmap says it is free "
                        "(hidden from allocation, or edited by hand)",
                        record=rn, seq=seq, lsn=lsn)]
    return []


def bitmap_bit(bitmap, i):
    o = i >> 3
    if bitmap is None or o >= len(bitmap):
        return None
    return bool(bitmap[o] & (1 << (i & 7)))


# ---------------------------------------------------------------- D3 LSN --
def rule_lsn_above_log(rn, lsn, log_highest, strict, seq=None):
    if lsn is None or log_highest is None or lsn <= log_highest:
        return []
    return [finding('D3', 'record_lsn_above_log', 'ntfs_integrity_lsn_checks',
                    'high' if strict else 'medium',
                    "The record's LSN is above every LSN in $LogFile - NTFS writes the log "
                    "first, so it cannot have written this record"
                    + ("" if strict else " (a live volume: read after the record, so still "
                                         "impossible, but kept at medium until lab-tested)"),
                    record=rn, seq=seq, lsn=lsn,
                    evidence={'record_lsn': lsn, 'log_highest_lsn': log_highest})]


# --------------------------------------------------- D4 / D5 volume facts --
def rule_usn_state(usn):
    """D4, single image: the journal's state as the volume reports it."""
    if not usn or not usn.get('available'):
        return []
    state = usn.get('state')
    if state == 'delete_in_progress':
        return [finding('D4', 'usn_journal_delete_in_progress', 'ntfs_integrity_usn_continuity',
                        'high', "The USN journal is being deleted (fsutil usn deletejournal, or "
                        "FSCTL_DELETE_USN_JOURNAL)", evidence=usn)]
    if state == 'not_active':
        return [finding('D4', 'usn_journal_not_active', 'ntfs_integrity_usn_continuity', 'medium',
                        "The volume has no active USN journal - deleted, disabled, or never "
                        "created (one image cannot tell which)", evidence=usn)]
    return []


def rule_logfile_state(logsum):
    """D5, single image: an empty log, or two restart copies that disagree.
    The clean flag and the log version are facts for the manifest, not
    findings (a live volume is never clean; Windows 8+ writes version 2.0)."""
    if not logsum or not logsum.get('available'):
        return []
    out = []
    if logsum.get('restart_pages_consistent') is False:
        out.append(finding('D5', 'restart_pages_disagree', 'ntfs_integrity_logfile_continuity',
                           'high', "The two $LogFile restart pages disagree, or one is damaged",
                           lsn=logsum.get('current_lsn'),
                           evidence={'restart_pages': logsum.get('restart_pages')}))
    if not logsum.get('record_pages'):
        out.append(finding('D5', 'logfile_has_no_record_pages', 'ntfs_integrity_logfile_continuity',
                           'medium', "$LogFile holds no log record pages - reset (ntfs-3g, "
                           "chkdsk /L) or never written", lsn=logsum.get('current_lsn'),
                           evidence={'empty_pages': logsum.get('empty_pages')}))
    return out


# ------------------------------------------------------- D1 change events --
def change_event(rn, old, new_header):
    """D1: what happened to a record between two parses. ``old`` is the
    previous map entry (full, semantic, lsn, seq, usa, flags, links)."""
    if old is None:
        return None
    o_flags, o_seq = old[5], old[3]
    o_present, o_in_use = bool(o_flags & dm.F_PRESENT), bool(o_flags & dm.F_IN_USE)
    present = new_header.get('present')
    in_use = bool(new_header.get('in_use'))
    seq = new_header.get('sequence')
    ev = {'previous_sequence': o_seq, 'sequence': seq if present else None,
          '_id_extra': 'from-%s' % o_seq}
    if o_present and not present:
        return finding('D1', 'record_cleared', 'ntfs_integrity_digest_map', 'info',
                       "The record slot held a FILE record at the last parse and holds none now",
                       record=rn, seq=o_seq, evidence=ev)
    if not present:
        return None
    if o_in_use and not in_use:
        return finding('D1', 'record_deleted', 'ntfs_integrity_digest_map', 'info',
                       "The record was in use at the last parse and is free now (deleted)",
                       record=rn, seq=seq, lsn=new_header.get('lsn'), evidence=ev)
    if in_use and o_present and (not o_in_use or o_seq != seq):
        return finding('D1', 'record_reused', 'ntfs_integrity_digest_map', 'info',
                       "The record holds a different file than at the last parse "
                       "(sequence %s -> %s)" % (o_seq, seq),
                       record=rn, seq=seq, lsn=new_header.get('lsn'), evidence=ev)
    return None


# ================================================================ the run ===
FULL_PARSE_REASONS = {
    'no_map': "no digest map from an earlier parse of this volume in this case",
    'map_tamper': "the digest map failed its seal (edited, damaged or truncated)",
    'map_unreadable': "the digest map could not be read",
    'map_key_unavailable': "the digest map was sealed with another user's key",
    'parser_version_changed': "the parser or digest format changed since the map was written",
    'record_size_changed': "the MFT record size changed",
    'mft_runlist_changed': "the $MFT runlist changed while its record count did not",
    'usn_journal_id_changed': "the USN journal ID changed (deleted and recreated)",
    'usn_journal_shrunk': "the USN journal's maximum size shrank",
    'usn_journal_missing': "the USN journal was active at the last parse and is not now",
    'usn_next_backwards': "the USN journal's next USN went backwards",
    'logfile_lsn_backwards': "the highest $LogFile LSN went backwards (an offline mount or a rollback)",
    'database_rows_missing': "the case database no longer holds this volume's rows from the last parse",
    'delta_parse_off': "the delta parse is turned off in Settings",
    'map_off': "neither the delta parse nor change tracking is on, so no map is kept",
    'integrity_unavailable': "the integrity checks could not start",
}


def fix_record(buf, h, record_size):
    """Fixups in place; False on a mismatch (the bytes are restored anyway)."""
    from utils.ntfs_runs import fixup_stride
    usa_off, usa_count = h.get('usa_offset', 0), h.get('usa_count', 0)
    if usa_count < 2 or usa_off < 0x2A or usa_off + 2 * usa_count > len(buf):
        return False
    stride = fixup_stride(record_size, usa_count)
    usn = bytes(buf[usa_off:usa_off + 2])
    ok = True
    for k in range(1, usa_count):
        e = k * stride - 2
        if e + 2 > len(buf):
            break
        if bytes(buf[e:e + 2]) != usn:
            ok = False
        buf[e:e + 2] = buf[usa_off + 2 * k:usa_off + 2 * k + 2]
    return ok


def full_digest(buf, h, key):
    """The FULL digest of a fixed-up record (LSN and update sequence zeroed)."""
    n = max(0x30, min(h.get('bytes_in_use') or len(buf), len(buf)))
    tmp = bytearray(buf[:n])
    tmp[0x08:0x10] = b'\0' * 8
    uo, uc = h.get('usa_offset', 0), h.get('usa_count', 0)
    e = min(n, uo + 2 * uc)
    if uo < e:
        tmp[uo:e] = b'\0' * (e - uo)
    import hashlib as _h
    return _h.blake2b(bytes(tmp), digest_size=dm.DIGEST_SIZE, key=key).digest() \
        if key else _h.blake2b(bytes(tmp), digest_size=dm.DIGEST_SIZE).digest()


def precompute_chunk(ctx, first, data, count):
    """What a worker can work out alone for ``count`` records of a full parse
    with no prior map (every record is new): per record the header, the
    fixup result, the FULL and SEMANTIC digests and the findings of the
    per-record rules, each list in the order the run would add them.

    Pure: the same functions IntegrityRun uses, on the same bytes. None when
    a record needs the parent - a live torn read is re-read from the volume,
    which only the parent holds - and the parent then scans the chunk itself.
    """
    rs = ctx['record_size']
    on = ctx['on']
    out = []
    for k in range(count):
        rn = first + k
        raw = data[k * rs:(k + 1) * rs]
        h = dm.record_header(raw)
        item = {'rn': rn, 'h': h, 'full': dm.ZERO_DIGEST, 'fixup_ok': False,
                'structure': [], 'semantic': None, 'rules': [], 'ext': None}
        if h['present']:
            buf = bytearray(raw)
            ok = fix_record(buf, h, rs)
            if not ok and not h['baad'] and ctx['source'] != 'file':
                return None
            item['fixup_ok'] = ok
            if on['ntfs_integrity_structural']:
                item['structure'] = list(rule_structure(rn, h, ok, reread=None, source=ctx['source']))
            if not h['baad']:
                item['full'] = full_digest(buf, h, ctx['key_full'])
                walked = dm.walk(buf, h)
                item['semantic'] = dm.semantic_digest(walked['parts'], ctx['key_semantic'] or b'')
                item['rules'], item['ext'] = _record_rule_findings(ctx, rn, h, walked)
        out.append(item)
    return out


def _record_rule_findings(ctx, rn, h, facts):
    """IntegrityRun._record_rules as data: the findings in order, and what it
    would tally for a record whose names partly sit elsewhere."""
    on = ctx['on']
    found, ext = [], None
    if on['ntfs_integrity_timestomp']:
        found.extend(rule_timestomp(rn, h, facts, ctx['now_ticks']))
    if on['ntfs_integrity_wipe_detect']:
        found.extend(rule_wiped(rn, h, facts))
    if on['ntfs_integrity_structural'] and h.get('in_use'):
        fn_count = len(facts.get('fns') or [])
        if h.get('base_record'):
            ext = ('ext', h['base_record'], fn_count)
        elif facts.get('has_attribute_list'):
            ext = ('attrlist', fn_count, _primary_name(facts.get('fns')))
        else:
            found.extend(rule_link_count(rn, h, fn_count, _primary_name(facts.get('fns'))))
    return found, ext


class IntegrityRun:
    """One volume, one parse. See the module docstring."""

    def __init__(self, *, volume, source, case_dir, record_size, record_count, identity,
                 settings=None, secret=None, key_store=None, reread=None, source_path=None,
                 parser_version=PARSER_VERSION):
        self.volume = str(volume)
        self.source = source                       # 'live' or 'file'
        self.source_path = source_path
        self.case_dir = case_dir
        self.record_size = int(record_size)
        self.record_count = int(record_count)
        self.identity = dict(identity or {})
        self.identity.setdefault('source', source)
        self.identity.setdefault('label', self.volume)
        self.parser_version = parser_version
        self.reread = reread
        self.settings = settings if settings is not None else read_settings()
        self.master = bool(self.settings.get('ntfs_integrity_enabled', True))
        self.on = {g: self.master and bool(self.settings.get(g, True)) for g in BUILT_CHECKS}
        self.delta_wanted = bool(self.settings.get('mft_delta_parse', True))
        self.need_map = self.delta_wanted or self.on['ntfs_integrity_digest_map']
        # Nothing to digest and nothing to check: the parse runs as before.
        self.idle = not self.need_map and not any(self.on.values())
        self._secret, self._key_store = secret, key_store
        self.keys = None
        self.prior = None
        self.prior_valid = False
        self.mode, self.reason = 'full', None
        self.map = None
        self.map_file = None
        self.manifest_id = '%s-%s' % (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()),
                                      uuid.uuid4().hex[:8])
        self.findings = []
        self._per_check = Counter()
        self._overflow = Counter()
        self.counts = Counter()
        self.replacements = {}                     # record -> re-read bytes
        self._attrlist_bases = {}                  # rn -> (header subset, local FN count, name)
        self._ext_fn = Counter()                   # base rn -> FN attributes in its extensions
        self.facts = {}
        self.wall_start = datetime.datetime.now(datetime.timezone.utc)
        self.mono_start = time.monotonic()
        self.now_ticks = int((time.time() + 86400) * 1e7) + 116444736000000000
        self.started = False
        self.error = None

    # ------------------------------------------------------------- begin --
    @property
    def volume_key(self):
        return '%s:%s' % (self.volume, dm.map_id(self.identity))

    def begin(self, db_conn=None, facts=None):
        """Load the previous map, check every full-parse trigger the desktop
        can see, and settle the mode. ``facts``: usn / logfile summaries as
        the volume reports them before the read."""
        self.facts['pre'] = dict(facts or {})
        self.started = True
        self.custody_disabled()
        if not self.need_map:
            self.mode, self.reason = 'full', 'map_off'
            return self.mode
        if self._secret is None:
            self._secret, self._key_store = dm.load_key(self.case_dir)
        self.keys = dm.Keys(self._secret, self._key_store or 'given')
        self.map_file = dm.map_path(self.case_dir, self.identity)
        prior, why = dm.DigestMap.load(self.map_file, self.keys)
        self.prior = prior
        if prior is None:
            self.mode, self.reason = 'full', why
        else:
            self.reason = self._trigger(prior.header, db_conn)
            if self.reason:
                self.mode = 'full'
            else:
                self.prior_valid = True
                if self.delta_wanted:
                    self.mode, self.reason = 'delta', None
                else:
                    self.mode, self.reason = 'full', 'delta_parse_off'
        self.map = dm.DigestMap(self.record_count)
        if self.reason and self.reason != 'delta_parse_off':
            self._custody('mft baseline reset', volume=self.volume, reason=self.reason,
                          reason_text=FULL_PARSE_REASONS.get(self.reason, self.reason),
                          map_file=self.map_file, manifest_id=self.manifest_id)
        return self.mode

    def _trigger(self, head, db_conn):
        """The first full-parse reason that holds, or None."""
        if head.get('parser_version') != self.parser_version:
            return 'parser_version_changed'
        if int(head.get('record_size') or 0) != self.record_size:
            return 'record_size_changed'
        if (head.get('runlist_hash') and self.identity.get('runlist_hash')
                and head.get('runlist_hash') != self.identity.get('runlist_hash')
                and int(head.get('record_count') or 0) == self.record_count):
            return 'mft_runlist_changed'
        old_usn, usn = head.get('usn') or {}, (self.facts['pre'].get('usn') or {})
        if old_usn.get('available') and usn.get('available'):
            if old_usn.get('state') == 'active' and usn.get('state') != 'active':
                return 'usn_journal_missing'
            if (old_usn.get('journal_id') is not None and usn.get('journal_id') is not None
                    and old_usn.get('journal_id') != usn.get('journal_id')):
                return 'usn_journal_id_changed'
            if (old_usn.get('max_size') and usn.get('max_size')
                    and usn['max_size'] < old_usn['max_size']):
                return 'usn_journal_shrunk'
            if (old_usn.get('next_usn') and usn.get('next_usn') is not None
                    and usn['next_usn'] < old_usn['next_usn']):
                return 'usn_next_backwards'
        old_log, log = head.get('logfile') or {}, (self.facts['pre'].get('logfile') or {})
        if (old_log.get('highest_lsn') and log.get('highest_lsn') is not None
                and log['highest_lsn'] < old_log['highest_lsn']):
            return 'logfile_lsn_backwards'
        if db_conn is not None:
            have = self._db_rows(db_conn)
            if not have or have < int(head.get('db_rows') or 0):
                return 'database_rows_missing'
        return None

    def _db_rows(self, db_conn):
        try:
            return db_conn.execute("SELECT COUNT(*) FROM mft_records WHERE volume_letter IS ?",
                                   (self.volume,)).fetchone()[0] or 0
        except Exception:                                    # noqa: BLE001
            return 0

    # -------------------------------------------------------------- scan --
    def scan_chunk(self, first, data, count=None):
        """Digest ``count`` consecutive records read from ``first``; return
        the set of those to parse, or None for "all of them" (a full parse)."""
        rs = self.record_size
        if count is None:
            count = len(data) // rs
        if self.idle:
            self.counts['records_read'] += count
            return None
        full_parse = self.mode != 'delta'
        want = None if full_parse else set()
        end = min(first + count, self.record_count)
        i = first
        while i < end:
            b = i // dm.BLOCK
            b_end = min((b + 1) * dm.BLOCK, end)
            recs = []
            for j in range(i, b_end):
                pos = (j - first) * rs
                recs.append(self._digest(j, data[pos:pos + rs]))
            block_complete = (b * dm.BLOCK >= i and b_end == min((b + 1) * dm.BLOCK, self.record_count))
            same_block = False
            if block_complete and self.map is not None:
                bd = dm.block_digest([r['full'] for r in recs], self.keys.block)
                self.map.set_block(b, bd)
                if self.prior_valid and self.prior.block_digest(b) == bd:
                    same_block = True
            for r in recs:
                self._settle(r, full_parse, same_block, want)
            i = b_end
        return want

    def worker_context(self):
        """What precompute_chunk needs, or None when the scan must stay here:
        nothing to scan, or a prior map to compare against (a delta parse
        decides what to parse from the digests, before the parse)."""
        if not self.started or self.idle or self.prior_valid or self.mode == 'delta':
            return None
        return {'record_size': self.record_size, 'on': dict(self.on), 'source': self.source,
                'now_ticks': self.now_ticks,
                'key_full': self.keys.full if self.keys else None,
                'key_semantic': self.keys.semantic if self.keys else None}

    def apply_chunk(self, first, count, pre):
        """scan_chunk, with each record's work done by precompute_chunk: the
        counts, findings, map entries and block digests come out as
        scan_chunk's would, in the same order. A full parse: returns None."""
        rs_count = self.record_count
        end = min(first + count, rs_count)
        i = first
        while i < end:
            b = i // dm.BLOCK
            b_end = min((b + 1) * dm.BLOCK, end)
            items = pre[i - first:b_end - first]
            for it in items:                                 # what _digest does
                self.counts['records_read'] += 1
                if it['h']['present']:
                    self.counts['file_records'] += 1
                for f in it['structure']:
                    self._add(f)
            block_complete = (b * dm.BLOCK >= i and b_end == min((b + 1) * dm.BLOCK, rs_count))
            if block_complete and self.map is not None:
                self.map.set_block(b, dm.block_digest([it['full'] for it in items], self.keys.block))
            for it in items:                                 # what _settle does
                self._settle_new(it)
            i = b_end
        return None

    def _settle_new(self, it):
        rn, h = it['rn'], it['h']
        flags = 0
        if h['present']:
            flags |= dm.F_PRESENT
            if h.get('in_use'):
                flags |= dm.F_IN_USE
            if it['fixup_ok']:
                flags |= dm.F_FIXUP_OK
            if h.get('baad'):
                flags |= dm.F_BAAD
            if not h.get('base_record'):
                flags |= dm.F_BASE
            if h.get('directory'):
                flags |= dm.F_DIRECTORY
        semantic = dm.ZERO_DIGEST
        if it['semantic'] is not None:
            semantic = it['semantic']
            flags |= dm.F_SEMANTIC
            self.counts['new_since_last_parse' if self.prior_valid else 'baseline'] += 1
        if self.map is not None:
            self.map.set(rn, it['full'], semantic, h.get('lsn') or 0, h.get('sequence') or 0,
                         h.get('usa_value') or 0, flags, h.get('links') or 0)
        if it['semantic'] is not None:
            for f in it['rules']:
                self._add(f)
            ext = it['ext']
            if ext is not None:
                if ext[0] == 'ext':
                    self._ext_fn[ext[1]] += ext[2]
                elif self.mode == 'full':
                    self._attrlist_bases[rn] = ({'in_use': True, 'base_record': 0,
                                                 'directory': h.get('directory'),
                                                 'links': h.get('links'), 'sequence': h.get('sequence'),
                                                 'lsn': h.get('lsn')}, ext[1], ext[2])

    def _digest(self, rn, raw):
        h = dm.record_header(raw)
        r = {'rn': rn, 'h': h, 'raw': raw, 'full': dm.ZERO_DIGEST, 'fixup_ok': False, 'buf': None}
        self.counts['records_read'] += 1
        if not h['present']:
            return r
        self.counts['file_records'] += 1
        buf = bytearray(raw)
        ok = self._fix(buf, h)
        reread = None
        if not ok and not h['baad'] and self.reread is not None:
            try:
                again = self.reread(rn)
                h2 = dm.record_header(again)
                buf2 = bytearray(again)
                if h2['present'] and self._fix(buf2, h2):
                    reread, buf, h, ok = True, buf2, h2, True
                    self.replacements[rn] = bytes(again)
                    r['raw'], r['h'] = again, h
                    self.counts['torn_reads_recovered'] += 1
                else:
                    reread = False
            except Exception:                                # noqa: BLE001
                reread = False
        elif not ok and not h['baad']:
            reread = None if self.source == 'file' else False
        r['fixup_ok'], r['buf'] = ok, buf
        if self.on['ntfs_integrity_structural']:
            for f in rule_structure(rn, h, ok, reread=reread, source=self.source):
                self._add(f)
        if not h['baad']:
            r['full'] = self._full(buf, h)
        return r

    def _fix(self, buf, h):
        """Fixups in place; False on a mismatch (the bytes are restored anyway)."""
        return fix_record(buf, h, self.record_size)

    def _full(self, buf, h):
        return full_digest(buf, h, self.keys.full if self.keys else None)

    def _settle(self, r, full_parse, same_block, want):
        rn, h = r['rn'], r['h']
        old = self.prior.get(rn) if self.prior_valid else None
        flags = 0
        if h['present']:
            flags |= dm.F_PRESENT
            if h.get('in_use'):
                flags |= dm.F_IN_USE
            if r['fixup_ok']:
                flags |= dm.F_FIXUP_OK
            if h.get('baad'):
                flags |= dm.F_BAAD
            if not h.get('base_record'):
                flags |= dm.F_BASE
            if h.get('directory'):
                flags |= dm.F_DIRECTORY
        semantic = dm.ZERO_DIGEST
        walked = None
        unchanged = (old is not None and (same_block or old[0] == r['full'])
                     and bool(old[5] & dm.F_PRESENT) == bool(h['present']))
        if unchanged:
            semantic = old[1]
            if old[5] & dm.F_SEMANTIC:
                flags |= dm.F_SEMANTIC
            self.counts['unchanged'] += 1
        elif h['present'] and not h.get('baad') and r['buf'] is not None:
            walked = dm.walk(r['buf'], h)
            semantic = dm.semantic_digest(walked['parts'], self.keys.semantic if self.keys
                                          else b'')
            flags |= dm.F_SEMANTIC
            if old is not None:
                if old[1] == semantic and old[5] & dm.F_SEMANTIC:
                    self.counts['noise_full_changed_semantic_same'] += 1
                else:
                    self.counts['semantic_changed'] += 1
                    if want is not None:
                        want.add(rn)
            else:
                self.counts['new_since_last_parse' if self.prior_valid else 'baseline'] += 1
                if want is not None:
                    want.add(rn)
        elif old is not None and bool(old[5] & dm.F_PRESENT) != bool(h['present']):
            self.counts['cleared_since_last_parse'] += 1
        if self.map is not None:
            self.map.set(rn, r['full'], semantic, h.get('lsn') or 0, h.get('sequence') or 0,
                         h.get('usa_value') or 0, flags, h.get('links') or 0)
        if self.prior_valid and self.on['ntfs_integrity_digest_map'] and old is not None:
            ev = change_event(rn, old, h)
            if ev:
                self.counts['change_' + ev['check']] += 1
                self._add(ev)
        if walked is not None:
            self._record_rules(rn, h, walked)

    def _record_rules(self, rn, h, facts):
        if self.on['ntfs_integrity_timestomp']:
            for f in rule_timestomp(rn, h, facts, self.now_ticks):
                self._add(f)
        if self.on['ntfs_integrity_wipe_detect']:
            for f in rule_wiped(rn, h, facts):
                self._add(f)
        if self.on['ntfs_integrity_structural'] and h.get('in_use'):
            fn_count = len(facts.get('fns') or [])
            if h.get('base_record'):
                self._ext_fn[h['base_record']] += fn_count
            elif facts.get('has_attribute_list'):
                if self.mode == 'full':
                    self._attrlist_bases[rn] = ({'in_use': True, 'base_record': 0,
                                                 'directory': h.get('directory'),
                                                 'links': h.get('links'), 'sequence': h.get('sequence'),
                                                 'lsn': h.get('lsn')},
                                                fn_count, _primary_name(facts.get('fns')))
            else:
                for f in rule_link_count(rn, h, fn_count, _primary_name(facts.get('fns'))):
                    self._add(f)

    def _add(self, f):
        key = (f['rule'], f['check'])
        self._per_check[key] += 1
        if self._per_check[key] > MAX_PER_CHECK:
            self._overflow[key] += 1
            return
        self.findings.append(f)

    def replacement(self, rn):
        """Bytes to parse instead of the first read (a torn read re-read)."""
        return self.replacements.get(rn)

    # ------------------------------------------------------------ finish --
    def finish(self, db_conn=None, post=None, write_rows=None):
        """The volume rules, the findings, the new map, the manifest."""
        post = dict(post or {})
        self.facts['post'] = post
        # Link counts of files whose names sit partly in extension records.
        for rn, (h, local, name) in self._attrlist_bases.items():
            for f in rule_link_count(rn, h, local + self._ext_fn.get(rn, 0), name):
                self._add(f)
        usn = post.get('usn') or self.facts['pre'].get('usn')
        logsum = post.get('logfile') or self.facts['pre'].get('logfile')
        if self.on['ntfs_integrity_usn_continuity']:
            for f in rule_usn_state(usn):
                self._add(f)
        if self.on['ntfs_integrity_logfile_continuity']:
            for f in rule_logfile_state(logsum):
                self._add(f)
        if self.map is not None:
            self._rebuild_blocks()
            self._map_rules(post.get('bitmap'), logsum)
        self._collapse()
        for (rule, check), n in self._overflow.items():
            self.findings.append(finding(
                rule, check + '_more', next((f['group'] for f in self.findings
                                             if f['rule'] == rule and f['check'] == check), ''),
                'info', "%d more %s.%s findings on this volume were counted but not listed "
                        "(the first %d are)" % (n, rule, check, MAX_PER_CHECK),
                evidence={'not_listed': n, '_id_extra': self.manifest_id}))
        self._fill_names(db_conn)
        rows = self.rows()
        written = 0
        if write_rows is not None and rows:
            try:
                written = write_rows(rows) or 0
            except Exception as e:                           # noqa: BLE001
                logger.error("NTFS integrity findings for %s not written: %s", self.volume, e)
                self.error = "findings not written: %s" % e
        self.counts['findings_written'] = written
        manifest = self._manifest(db_conn, logsum, usn)
        self._custody_findings()
        self._custody('ntfs integrity manifest', **manifest)
        return manifest

    def _rebuild_blocks(self):
        """Every block digest from the entries: a chunk boundary inside a
        block left that block undigested during the scan."""
        keyb = self.keys.block if self.keys else b''
        ents, size = self.map.entries, dm.ENTRY_SIZE
        for b in range((self.record_count + dm.BLOCK - 1) // dm.BLOCK):
            lo, hi = b * dm.BLOCK, min((b + 1) * dm.BLOCK, self.record_count)
            self.map.set_block(b, dm.block_digest(
                [bytes(ents[i * size:i * size + dm.DIGEST_SIZE]) for i in range(lo, hi)], keyb))

    # A rule that fires on a large share of the volume is describing the
    # volume, not files: a $MFT copied out already fixed up, a reset or
    # rolled-back $LogFile, a bitmap from another moment. One volume finding
    # then, not a thousand record findings.
    _COLLAPSE = {('D7', 'si_created_before_fn_created'):
                 "$STANDARD_INFORMATION created is earlier than $FILE_NAME created on a large "
                 "share of this volume. Files deployed from a Windows or OEM image, and files an "
                 "installer, archive or copy tool wrote with their source's creation time, look "
                 "like this (SI keeps the source's time, FN takes the date the file was written "
                 "here), so record by record it does not single out a timestomp. Compare "
                 "mft_standard_info.created_filetime with mft_file_names.created_filetime to "
                 "list them",
                 ('D7', 'si_mft_changed_before_fn_created'):
                 "$STANDARD_INFORMATION created and MFT-entry-changed are both earlier than "
                 "$FILE_NAME created on a large share of this volume. Files restored from an image "
                 "or brought over with all their times kept look like this, many at once and in "
                 "one sitting, so record by record it does not single out a timestomp. Compare "
                 "mft_standard_info.created_filetime and mft_modified_filetime with "
                 "mft_file_names.created_filetime to list them",
                 ('D10', 'fixup_mismatch'): "Most records fail their update-sequence check - "
                                            "the copy was most likely taken already fixed up, "
                                            "not tampered record by record",
                 ('D3', 'record_lsn_above_log'): "Most records carry an LSN above every LSN in "
                                                 "$LogFile - the log was reset or rolled back "
                                                 "(an offline mount, chkdsk /L, a restore)",
                 ('D29', 'record_in_use_bitmap_free'): "Most in-use records are free in the $MFT "
                                                       "bitmap - the bitmap read does not match "
                                                       "this $MFT",
                 ('D29', 'bitmap_allocated_record_free'): "Most free records are allocated in the "
                                                          "$MFT bitmap - the bitmap read does not "
                                                          "match this $MFT"}

    # The share of the volume above which a rule describes the volume. The D7
    # comparisons are common on any Windows install (1.5% and 4.2% of the
    # build host's C:), so they collapse earlier: a full parse then reports
    # the pattern once, and a delta parse - a few changed records - still
    # lists every file that newly shows it.
    _COLLAPSE_SHARE = {('D7', 'si_created_before_fn_created'): 0.01,
                       ('D7', 'si_mft_changed_before_fn_created'): 0.01}

    def _collapse(self, share=0.10, minimum=1000):
        base = max(1, self.counts.get('file_records', 0))
        for key, text in self._COLLAPSE.items():
            n = self._per_check.get(key, 0)
            if n < minimum or n < self._COLLAPSE_SHARE.get(key, share) * base:
                continue
            rule, check = key
            group = next((f['group'] for f in self.findings
                          if f['rule'] == rule and f['check'] == check), '')
            self.findings = [f for f in self.findings
                             if not (f['rule'] == rule and f['check'] == check)]
            self._overflow.pop(key, None)
            sev = {'D10': 'medium', 'D7': 'low'}.get(rule, 'high')
            self.findings.append(finding(rule, check + '_volume', group, sev,
                                         "%s (%d of %d records)." % (text, n, base),
                                         evidence={'records': n, 'file_records': base,
                                                   '_id_extra': self.manifest_id}))
            self.counts['collapsed_' + check] = n

    def _map_rules(self, bitmap, logsum):
        """D3 and D29 over every record, from the map's entries."""
        log_hi = (logsum or {}).get('highest_lsn') if (logsum or {}).get('record_pages') else None
        strict = self.source == 'file' or bool((logsum or {}).get('clean'))
        lsn_on = self.on['ntfs_integrity_lsn_checks']
        bm_on = bitmap is not None and (self.on['ntfs_integrity_structural']
                                        or self.on['ntfs_integrity_wipe_detect'])
        if not lsn_on and not bm_on:
            return
        if lsn_on and log_hi is None:
            self.counts['d3_skipped_no_log'] = 1
        ent = dm.ENTRY
        candidates = []
        for rn in range(self.record_count):
            full, sem, lsn, seq, usa, flags, links = ent.unpack_from(self.map.entries, rn * dm.ENTRY_SIZE)
            present = bool(flags & dm.F_PRESENT)
            if lsn_on and log_hi is not None and present:
                for f in rule_lsn_above_log(rn, lsn, log_hi, strict, seq=seq):
                    self._add(f)
            if bm_on and rn >= FIRST_RECORD_CHECKED:
                alloc = bitmap_bit(bitmap, rn)
                if alloc is None:
                    continue
                candidates.extend(rule_bitmap(rn, alloc, bool(flags & dm.F_IN_USE), present,
                                              seq=seq if present else None,
                                              lsn=lsn if present else None,
                                              wipe_on=self.on['ntfs_integrity_wipe_detect'],
                                              structural_on=self.on['ntfs_integrity_structural']))
        for f in self._confirm_bitmap(candidates):
            self._add(f)

    def _confirm_bitmap(self, candidates):
        """A live volume's bitmap and records are written lazily and not
        together: a record allocated seconds before the bitmap was read shows
        as "in use, bitmap free" (the first live read flagged the probe's own
        new folder). On a live volume each candidate is judged again on a
        fresh bitmap and a fresh read of the record; only what still
        disagrees is reported. A file copy is static: judged as read."""
        reread_bitmap = self.facts.get('post', {}).get('reread_bitmap')
        if not candidates or self.source != 'live' or reread_bitmap is None or self.reread is None:
            return candidates
        if len(candidates) > 5000:          # a volume-wide mismatch: _collapse says so
            return candidates
        try:
            fresh = reread_bitmap()
        except Exception:                                    # noqa: BLE001
            return candidates
        if fresh is None:
            return candidates
        kept = []
        for f in candidates:
            rn = f['record_number']
            try:
                h = dm.record_header(self.reread(rn))
            except Exception:                                # noqa: BLE001
                kept.append(f)
                continue
            again = rule_bitmap(rn, bitmap_bit(fresh, rn), bool(h.get('in_use')), h.get('present'),
                                seq=h.get('sequence'), lsn=h.get('lsn'),
                                wipe_on=self.on['ntfs_integrity_wipe_detect'],
                                structural_on=self.on['ntfs_integrity_structural'])
            if not any(a['check'] == f['check'] for a in again):
                self.counts['bitmap_race_cleared_by_reread'] += 1
                continue
            f.setdefault('evidence', {})['confirmed_by_reread'] = True
            # Even a confirmed mismatch is weak on a live volume: the bitmap
            # page of a record deleted minutes earlier was still unflushed on
            # the build host after a re-read, and a checkpoint LSN does not
            # promise a flush (NTFS checkpoints are fuzzy). Kept, as low; a
            # mismatch that persists to the next parse is a later check (M3).
            f['severity'] = 'low'
            f['detail'] += (" (live volume: the bitmap on disk can lag its record by minutes, "
                            "so one reading is not conclusive)")
            self.counts['bitmap_mismatch_live'] += 1
            kept.append(f)
        return kept

    def _fill_names(self, db_conn):
        if db_conn is None:
            return
        for f in self.findings:
            if f.get('file_name') or f.get('record_number') is None:
                continue
            try:
                row = db_conn.execute(
                    "SELECT file_name FROM mft_records WHERE record_number = ? AND volume_letter IS ?",
                    (f['record_number'], self.volume)).fetchone()
                if row and row[0]:
                    f['file_name'] = row[0]
            except Exception:                                # noqa: BLE001
                return

    def rows(self):
        """The findings as ntfs_integrity_findings rows (FINDING_COLUMNS order),
        unique by finding_id."""
        from utils.time_utils import get_current_forensic_timestamp
        parsed_at = get_current_forensic_timestamp()
        seen, out = set(), []
        vkey = self.volume_key
        for f in self.findings:
            fid = finding_id(f, vkey)
            if fid in seen:
                continue
            seen.add(fid)
            ev = {k: v for k, v in (f.get('evidence') or {}).items() if not k.startswith('_')}
            out.append((fid, self.volume, vkey, f['rule'], f['check'], f['group'], f['severity'],
                        f.get('record_number'), f.get('sequence_number'), f.get('lsn'),
                        f.get('file_name'), f['detail'], json.dumps(ev, sort_keys=True, default=str),
                        self.manifest_id, self.mode, parsed_at))
        return out

    def _manifest(self, db_conn, logsum, usn):
        root = prev_root = prev_chain = None
        if self.prior is not None:
            prev_root = self.prior.header.get('merkle_root')
            prev_chain = self.prior.header.get('chain')
        if self.map is not None:
            root = self.map.merkle_root()
        by_check = Counter()
        for (rule, check), n in self._per_check.items():
            by_check['%s.%s' % (rule, check)] += n
        mono_end = time.monotonic()
        manifest = OrderedDict([
            ('format', MANIFEST_FORMAT),
            ('manifest_id', self.manifest_id),
            ('volume', self.volume),
            ('source', self.source),
            ('source_path', self.source_path),
            ('identity', dict(self.identity, map_id=dm.map_id(self.identity),
                              record_size=self.record_size, record_count=self.record_count)),
            ('versions', {'parser': self.parser_version, 'digest_format': dm.FORMAT_VERSION,
                          'crow_eye': _crow_eye_version()}),
            ('policy', {'settings': dict(self.settings), 'hash': policy_hash(self.settings),
                        'master': self.master,
                        'checks': {g: ('on' if self.on[g] else 'off') for g in BUILT_CHECKS},
                        'not_built_in_this_version': [k for k in SETTING_DEFAULTS
                                                      if k not in BUILT_CHECKS and k not in
                                                      ('ntfs_integrity_enabled', 'mft_delta_parse',
                                                       'ntfs_integrity_usn_witness_mode')],
                        'allowlists': None}),
            ('mode', self.mode),
            ('reason', self.reason),
            ('reason_text', FULL_PARSE_REASONS.get(self.reason) if self.reason else None),
            ('usn_journal', usn or {'available': False}),
            ('logfile', logsum or {'available': False}),
            ('logfile_before_read', self.facts['pre'].get('logfile')),
            ('host_settings', self.facts['pre'].get('host_settings')
             or self.facts['post'].get('host_settings')),
            ('bitmap', {'available': self.facts['post'].get('bitmap') is not None,
                        'note': self.facts['post'].get('bitmap_note')}),
            ('counts', dict(self.counts)),
            ('findings', dict(by_check)),
            ('findings_not_listed', {'%s.%s' % k: n for k, n in self._overflow.items()}),
            ('map', {'file': self.map_file, 'kept': self.need_map,
                     'key_store': self.keys.store if self.keys else None,
                     'merkle_root': root, 'previous_merkle_root': prev_root}),
            ('prev_chain', prev_chain),
            ('wall_utc_start', self.wall_start.strftime('%Y-%m-%dT%H:%M:%S.%fZ')),
            ('wall_utc_end', datetime.datetime.now(datetime.timezone.utc)
             .strftime('%Y-%m-%dT%H:%M:%S.%fZ')),
            ('monotonic_seconds', round(mono_end - self.mono_start, 3)),
            ('minifilters', "not recorded by the desktop parser (Sentinel records them)"),
            ('error', self.error),
        ])
        manifest['chain'] = dm.chain_value(prev_chain, root, manifest) if root else None
        if self.map is not None and self.error is None:
            self.map.header.update({
                'parser_version': self.parser_version, 'record_size': self.record_size,
                'runlist_hash': self.identity.get('runlist_hash'), 'identity': self.identity,
                'volume': self.volume, 'source': self.source,
                'usn': usn or {'available': False},
                'logfile': {'highest_lsn': (logsum or {}).get('highest_lsn'),
                            'current_lsn': (logsum or {}).get('current_lsn')},
                'db_rows': self._db_rows(db_conn) if db_conn is not None else None,
                'chain': manifest['chain'], 'manifest_id': self.manifest_id})
            try:
                self.map.save(self.map_file, self.keys)
                manifest['map']['written'] = True
            except Exception as e:                           # noqa: BLE001
                manifest['map']['written'] = False
                manifest['map']['error'] = str(e)
                logger.error("Digest map for %s not written: %s", self.volume, e)
        return manifest

    # ----------------------------------------------------------- custody --
    def _custody(self, event, **fields):
        """Into the case's chain-of-custody ledger; never raises."""
        try:
            from utils import custody
            custody.ledger(self.case_dir, event, **fields)
        except Exception:                                    # noqa: BLE001
            pass

    def _warn(self, message):
        try:
            from utils import custody
            custody.warn(message)
        except Exception:                                    # noqa: BLE001
            pass

    def custody_disabled(self):
        """'integrity check disabled' for every check that is off - at every
        parse, so a silenced check never reads as a clean result."""
        off = [g for g in BUILT_CHECKS if not self.on[g]]
        for g in off:
            self._custody('integrity check disabled', volume=self.volume, check=g,
                          rules=BUILT_CHECKS[g][0], label=BUILT_CHECKS[g][1],
                          master_switch=self.master, manifest_id=self.manifest_id)
        if off:
            self._warn("NTFS integrity on %s: %d check(s) turned off in Settings (%s) - their "
                       "absence of findings is not a clean result."
                       % (self.volume, len(off), ", ".join(BUILT_CHECKS[g][0] for g in off)))
        return off

    def _custody_findings(self, limit=50):
        high = [f for f in self.findings if f['severity'] == 'high']
        vkey = self.volume_key
        for f in high[:limit]:
            self._custody('integrity finding', volume=self.volume, finding_id=finding_id(f, vkey),
                          rule=f['rule'], check=f['check'], severity=f['severity'],
                          record_number=f.get('record_number'), sequence_number=f.get('sequence_number'),
                          lsn=f.get('lsn'), file_name=f.get('file_name'), detail=f['detail'],
                          manifest_id=self.manifest_id)
        if len(high) > limit:
            self._custody('integrity finding', volume=self.volume, severity='high',
                          summary=True, listed=limit, total_high=len(high),
                          note="the rest are in the ntfs_integrity_findings table",
                          manifest_id=self.manifest_id)
        if high:
            self._warn("NTFS integrity on %s: %d high-severity finding(s) - see the "
                       "ntfs_integrity_findings table." % (self.volume, len(high)))


def _crow_eye_version():
    try:
        from utils import custody
        return custody._tool_version()
    except Exception:                                        # noqa: BLE001
        return None


# ----------------------------------------------------------- the findings table --
FINDING_COLUMNS = ['finding_id', 'volume_letter', 'volume_id', 'rule', 'check_name',
                   'check_group', 'severity', 'record_number', 'sequence_number', 'lsn',
                   'file_name', 'detail', 'evidence', 'manifest_id', 'parse_mode', 'parsed_at']
