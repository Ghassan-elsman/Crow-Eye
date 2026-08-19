r"""Replay a registry hive's transaction logs, so a dirty hive is not read as final.

A hive that Windows had open is almost never the whole story. Its base block
carries two sequence numbers, at 0x04 and 0x08; when they differ, Windows was
mid-transaction and the outstanding changes are in the `.LOG1` / `.LOG2` files
beside it. Neither library Crow-Eye has will apply them - `python-registry`
ignores the condition, and `dissect.regf` detects it and logs "recovery needed"
and stops - so an offline parse silently reported a stale registry.

On this machine every dirty hive looked, at first, unrecoverable:

    hive          seq1 / seq2            LOG1 first entry   apparent gap
    SYSTEM        1888230 / 1888229      1889322            1092
    SOFTWARE      5102671 / 5102670      5104537            1866
    NTUSER.DAT     365687 /  365686       366244             557

That reads as a thousand lost transactions, and applying the entries anyway
would write pages onto a hive state they were never computed against. The
opposite reading - that the base block simply lags while the body is current -
demands the opposite behaviour. The bytes cannot settle it, so it was settled
against msuhanov's `yarp`, the reference implementation the published format
documentation comes from: yarp recovers all of these hives without complaint.

**The gap is not a gap.** Log entries are contiguous from the *log file's own*
base-block sequence number, not from the hive's, and a log is eligible whenever
its sequence is at or ahead of the hive's secondary - only a log *older* than
the hive is refused. That is the rule implemented below, and it is written down
here so nobody has to re-derive it from a hex editor.

Checked, not assumed. Against yarp on all seven hives of this machine, acquired
from one VSS snapshot: the five dirty ones recover BYTE-IDENTICALLY (SYSTEM 87
entries, SOFTWARE 250, NTUSER.DAT 69, UsrClass.dat 36, DEFAULT 17), and both
implementations decline the two clean ones. Seven agreements, no disagreements,
with the source hives' SHA-256 unchanged either side of the run. The Marvin32
below reproduces the hashes stored in real log entries exactly, which is what
says the entry offsets are right as well as the algorithm.

Nothing here modifies evidence. Recovery reads the originals read-only and
writes a recovered copy elsewhere; the caller owns that copy's lifetime.
"""

import logging
import os
import struct

logger = logging.getLogger(__name__)

# A primary hive's base block occupies the first 4096 bytes; hive bins follow.
# In a log file the base block is only 512 bytes and log entries follow it.
PRIMARY_BASE_BLOCK_LEN = 4096
LOG_BASE_BLOCK_LEN = 512

HIVE_SIGNATURE = b"regf"
LOG_ENTRY_SIGNATURE = b"HvLE"
OLD_LOG_SIGNATURE = b"DIRT"

# Offsets inside a base block.
_OFF_SEQ1 = 0x04
_OFF_SEQ2 = 0x08
_OFF_HBINS_SIZE = 0x28
_OFF_CHECKSUM = 508

# A log entry header, and the size of one dirty-page reference.
_LOG_ENTRY_HEADER_LEN = 40
_DIRTY_PAGE_REF_LEN = 8

# Seed Windows uses for the Marvin32 checksums in a log entry.
_MARVIN_SEED = 0x82EF4D887A4E55C5

_U32 = 0xFFFFFFFF


class RecoveryResult(object):
    """What happened to one hive, in a form a database row can be built from.

    Every field is filled whether recovery ran or not. A parse that could not
    recover still has to be able to say why, because "these rows may not be the
    final registry" is the analyst's call to make, not the parser's to hide.
    """

    def __init__(self, hive_path):
        self.hive_path = hive_path
        self.hive_name = os.path.basename(hive_path)
        self.sequence_1 = None
        self.sequence_2 = None
        self.was_dirty = None
        self.logs_found = []
        self.log_format = ""          # "new" (HvLE), "old" (DIRT), or ""
        self.recovered = False
        self.recovered_path = ""
        self.pages_applied = 0
        self.entries_applied = 0
        self.highest_sequence = None
        self.reason = ""

    def __repr__(self):
        return ("<RecoveryResult %s dirty=%s recovered=%s pages=%d reason=%r>"
                % (self.hive_name, self.was_dirty, self.recovered,
                   self.pages_applied, self.reason))


def _rotl32(value, count):
    value &= _U32
    return ((value << count) | (value >> (32 - count))) & _U32


def _marvin32_mix(lo, hi):
    hi ^= lo
    lo = _rotl32(lo, 20)
    lo = (lo + hi) & _U32
    hi = _rotl32(hi, 9)
    hi ^= lo
    lo = _rotl32(lo, 27)
    lo = (lo + hi) & _U32
    hi = _rotl32(hi, 19)
    return lo, hi


def marvin32(data, seed=_MARVIN_SEED):
    """Marvin32 hash, the integrity check Windows puts in every log entry.

    A log entry carries two of these: one over its header, one over its body.
    They are what distinguishes a real entry from whatever bytes happen to sit
    after the last one - the log file is not truncated, so the tail is always
    the previous generation's data, and a parser that trusts the signature
    alone will happily apply garbage.
    """
    lo = seed & _U32
    hi = (seed >> 32) & _U32

    length = len(data)
    pos = 0
    while length >= 4:
        lo = (lo + struct.unpack_from("<I", data, pos)[0]) & _U32
        lo, hi = _marvin32_mix(lo, hi)
        pos += 4
        length -= 4

    # The tail is padded with a 0x80 byte, then hashed like any other word.
    tail = 0x80
    if length == 3:
        tail = (0x80 << 24) | (data[pos + 2] << 16) | (data[pos + 1] << 8) | data[pos]
    elif length == 2:
        tail = (0x80 << 16) | (data[pos + 1] << 8) | data[pos]
    elif length == 1:
        tail = (0x80 << 8) | data[pos]

    lo = (lo + tail) & _U32
    lo, hi = _marvin32_mix(lo, hi)
    lo, hi = _marvin32_mix(lo, hi)
    return ((hi << 32) | lo) & 0xFFFFFFFFFFFFFFFF


def base_block_checksum(block):
    """XOR-32 over the first 508 bytes, the checksum a base block stores at 508.

    0 and 0xFFFFFFFF are both reserved, so Windows nudges them by one. Getting
    that wrong produces a hive every tool rejects.
    """
    checksum = 0
    for offset in range(0, 508, 4):
        checksum ^= struct.unpack_from("<I", block, offset)[0]
    if checksum == 0:
        return 1
    if checksum == _U32:
        return 0xFFFFFFFE
    return checksum


def read_base_block(path):
    """The interesting fields of a hive or log base block, or None.

    Returns a dict rather than a tuple: callers want different fields and a
    positional read of eight values is where transcription errors live.
    """
    try:
        with open(path, "rb") as handle:
            block = handle.read(LOG_BASE_BLOCK_LEN)
    except OSError as exc:
        logger.debug("Cannot read base block of %s: %s", path, exc)
        return None

    if len(block) < LOG_BASE_BLOCK_LEN or block[:4] != HIVE_SIGNATURE:
        return None

    seq1, seq2 = struct.unpack_from("<II", block, _OFF_SEQ1)
    stored = struct.unpack_from("<I", block, _OFF_CHECKSUM)[0]
    return {
        "sequence_1": seq1,
        "sequence_2": seq2,
        "hbins_size": struct.unpack_from("<I", block, _OFF_HBINS_SIZE)[0],
        "checksum_stored": stored,
        "checksum_ok": stored == base_block_checksum(block),
        "is_dirty": seq1 != seq2,
    }


def log_format_of(log_path):
    """"new" for an HvLE log, "old" for a DIRT one, "" for neither.

    The old format is reported rather than parsed. Windows 7 and earlier wrote
    it, and mis-reading it as the new format would apply the wrong bytes to the
    wrong offsets - a silent corruption, which is the failure mode worth
    spending a branch on.
    """
    try:
        with open(log_path, "rb") as handle:
            head = handle.read(PRIMARY_BASE_BLOCK_LEN)
    except OSError:
        return ""
    # A base block is all that is required to classify. Demanding the first log
    # entry as well would report a truncated log as unrecognised, which reads as
    # "no log here" rather than as the damaged log it is.
    if len(head) < LOG_BASE_BLOCK_LEN or head[:4] != HIVE_SIGNATURE:
        return ""
    if head[LOG_BASE_BLOCK_LEN:LOG_BASE_BLOCK_LEN + 4] == LOG_ENTRY_SIGNATURE:
        return "new"
    if OLD_LOG_SIGNATURE in head[:LOG_BASE_BLOCK_LEN]:
        return "old"
    return ""


def _parse_log_entry(buffer, position, expected_sequence):
    """One validated log entry, or None if this is not one.

    `expected_sequence` is what makes the chain a chain. Entries run
    consecutively from the log file's own base-block sequence number, and an
    entry out of that order means the chain has ended and the rest of the file
    is the previous generation - not an error, just the end.
    """
    if position + _LOG_ENTRY_HEADER_LEN > len(buffer):
        return None

    (signature, size, flags, sequence, hbins_size,
     dirty_count) = struct.unpack_from("<4sIIIII", buffer, position)

    if signature != LOG_ENTRY_SIGNATURE:
        return None
    # A log entry is always a whole number of 512-byte sectors.
    if size < LOG_BASE_BLOCK_LEN or size % LOG_BASE_BLOCK_LEN:
        return None
    if position + size > len(buffer):
        return None
    if sequence != expected_sequence:
        return None
    if dirty_count == 0:
        return None

    refs_end = _LOG_ENTRY_HEADER_LEN + dirty_count * _DIRTY_PAGE_REF_LEN
    if refs_end > size:
        return None

    entry = buffer[position:position + size]
    hash1, hash2 = struct.unpack_from("<QQ", entry, 24)
    if marvin32(entry[_LOG_ENTRY_HEADER_LEN:]) != hash1:
        return None
    if marvin32(entry[:32]) != hash2:
        return None

    pages = []
    cursor = refs_end
    for index in range(dirty_count):
        page_offset, page_size = struct.unpack_from(
            "<II", entry, _LOG_ENTRY_HEADER_LEN + index * _DIRTY_PAGE_REF_LEN)
        if cursor + page_size > size:
            return None
        pages.append((PRIMARY_BASE_BLOCK_LEN + page_offset,
                      entry[cursor:cursor + page_size]))
        cursor += page_size

    return {
        "sequence": sequence,
        "size": size,
        "flags": flags,
        "hbins_size": hbins_size,
        "pages": pages,
    }


def read_log_entries(log_path):
    """Every valid, in-order log entry in a new-format log file.

    The chain starts at the log's own base-block sequence number. That is the
    detail the whole design turned on: measured against the HIVE's sequence
    these entries look a thousand transactions adrift and unusable, and they
    are neither.
    """
    base = read_base_block(log_path)
    if base is None:
        return []
    try:
        with open(log_path, "rb") as handle:
            buffer = handle.read()
    except OSError as exc:
        logger.debug("Cannot read log %s: %s", log_path, exc)
        return []

    entries = []
    position = LOG_BASE_BLOCK_LEN
    expected = base["sequence_1"]
    while position < len(buffer):
        entry = _parse_log_entry(buffer, position, expected)
        if entry is None:
            break
        entries.append(entry)
        position += entry["size"]
        expected = (expected + 1) & _U32
    return entries


def find_logs_for(hive_path):
    """The .LOG1 / .LOG2 sitting beside a hive, whatever their case.

    Collected evidence keeps whatever case the source filesystem had, and a
    case-sensitive guess here would find nothing on a mounted image while
    working fine on Windows.
    """
    directory = os.path.dirname(hive_path) or "."
    stem = os.path.basename(hive_path)
    wanted = {(stem + ext).lower(): None for ext in (".LOG1", ".LOG2")}
    try:
        for name in os.listdir(directory):
            if name.lower() in wanted:
                wanted[name.lower()] = os.path.join(directory, name)
    except OSError as exc:
        logger.debug("Cannot list %s: %s", directory, exc)
        return []
    return [path for _, path in sorted(wanted.items()) if path]


def recover_hive(hive_path, output_path, log_paths=None):
    """Apply a hive's transaction logs into a recovered copy at `output_path`.

    The original is opened read-only and never written to; `output_path` gets
    the recovered hive, and only when recovery actually happened. A clean hive,
    a missing log, an old-format log and a log older than the hive all return a
    result with `recovered` False and a `reason` - the caller parses the
    original in every one of those cases rather than losing the evidence.
    """
    result = RecoveryResult(hive_path)

    base = read_base_block(hive_path)
    if base is None:
        result.reason = "not a registry hive"
        return result

    result.sequence_1 = base["sequence_1"]
    result.sequence_2 = base["sequence_2"]
    result.was_dirty = base["is_dirty"]

    if not base["is_dirty"]:
        result.reason = "hive was closed cleanly; nothing to replay"
        return result

    if log_paths is None:
        log_paths = find_logs_for(hive_path)
    result.logs_found = list(log_paths)
    if not log_paths:
        result.reason = "hive is dirty but no transaction log was collected"
        return result

    # Gather the candidate logs, rejecting the ones that cannot apply.
    candidates = []
    for path in log_paths:
        fmt = log_format_of(path)
        if fmt == "old":
            result.log_format = result.log_format or "old"
            result.reason = ("transaction log is the pre-Windows 8 DIRT format, "
                             "which is not replayed")
            continue
        if fmt != "new":
            continue
        result.log_format = "new"
        log_base = read_base_block(path)
        if log_base is None:
            continue
        # Only a log OLDER than the hive is unusable. A log far AHEAD of the
        # hive's base block is the normal state of a running system.
        if log_base["sequence_1"] < base["sequence_2"]:
            continue
        entries = read_log_entries(path)
        if entries:
            candidates.append((log_base["sequence_1"], path, entries))

    if not candidates:
        if not result.reason:
            result.reason = "no transaction log applies to this hive"
        return result

    # Oldest first, and the second log must carry on from where the first
    # stopped. Windows alternates between the two, so a pair that does not join
    # up means one of them belongs to an older generation.
    candidates.sort(key=lambda item: item[0])
    applied = []
    last_sequence = None
    for start_sequence, path, entries in candidates[:2]:
        if last_sequence is not None and start_sequence <= last_sequence:
            continue
        applied.append((path, entries))
        last_sequence = entries[-1]["sequence"]

    if not applied:
        result.reason = "no transaction log applies to this hive"
        return result

    try:
        with open(hive_path, "rb") as source:
            image = bytearray(source.read())
    except OSError as exc:
        result.reason = "cannot read hive: %s" % exc
        return result

    pages = 0
    entry_count = 0
    hbins_size = base["hbins_size"]
    for _path, entries in applied:
        for entry in entries:
            entry_count += 1
            hbins_size = entry["hbins_size"]
            for offset, data in entry["pages"]:
                end = offset + len(data)
                if end > len(image):
                    # The log grew the hive; extend rather than silently
                    # dropping the tail of a page.
                    image.extend(b"\x00" * (end - len(image)))
                image[offset:end] = data
                pages += 1

    # The recovered hive is clean, as of the last sequence applied, and its
    # base block has to say so or every reader will still call it dirty.
    struct.pack_into("<II", image, _OFF_SEQ1, last_sequence, last_sequence)
    struct.pack_into("<I", image, _OFF_HBINS_SIZE, hbins_size)
    struct.pack_into("<I", image, _OFF_CHECKSUM,
                     base_block_checksum(bytes(image[:LOG_BASE_BLOCK_LEN])))

    try:
        with open(output_path, "wb") as destination:
            destination.write(image)
    except OSError as exc:
        result.reason = "cannot write recovered hive: %s" % exc
        return result

    result.recovered = True
    result.recovered_path = output_path
    result.pages_applied = pages
    result.entries_applied = entry_count
    result.highest_sequence = last_sequence
    result.reason = "replayed %d entries from %d log file(s)" % (
        entry_count, len(applied))
    return result
