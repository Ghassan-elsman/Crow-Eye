"""Pre-flight checks for forensic image parsing.

Everything an investigator can get wrong, and everything wrong with an image,
found before extraction starts and named in the investigator's terms - not a
traceback, not "completed successfully, 0 artifacts".

Pure functions over bytes and paths (no Qt, no dissect), so every check is
unit-testable on synthetic headers:

    sniff_format(path)            what the bytes say the file is
    check_segments(paths)         first segment chosen? any segment missing?
    preflight_image(paths)        both, plus extension/content mismatch -> issues
    classify_boot_sector(data)    BitLocker / NTFS / FAT / exFAT / ReFS / unknown
    partition_issues(partitions)  BitLocker, no file system, no Windows -> issues
    check_case(case_root, ...)    writable, not holding the image, enough space
    issue_for_open_error(exc)     an exception opening the image -> one issue

Each issue is a utils.parse_status.SessionIssue, so it lands in the Parse Status
Report beside the per-artifact outcomes.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

try:
    from utils.parse_status import SessionIssue, make_issue
except ImportError:  # pragma: no cover - standalone use without the app root
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from utils.parse_status import SessionIssue, make_issue

logger = logging.getLogger("image_parsing.preflight")

# --------------------------------------------------------------------------
# Format sniffing
# --------------------------------------------------------------------------

SUPPORTED = ("E01", "EX01", "VHDX", "VHD", "VMDK", "ISO", "RAW")

# Formats recognised by their signature that Crow-Eye cannot open, named so the
# investigator knows what they have.
_UNSUPPORTED_SIGS = (
    (0, b"LVF\x09\x0d\x0a\xff\x00", "EnCase logical evidence (L01)"),
    (0, b"LEF2\x0d\x0a\x81\x00", "EnCase logical evidence (Lx01)"),
    (0, b"AFF10\x0d\x0a", "Advanced Forensic Format (AFF)"),
    (0, b"ADSEGMENTEDFILE", "AccessData logical image (AD1)"),
    (0, b"PK\x03\x04", "ZIP archive"),
    (0, b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
    (0, b"Rar!\x1a\x07", "RAR archive"),
    (0, b"\x1f\x8b", "gzip-compressed file"),
    (0, b"BZh", "bzip2-compressed file"),
    (0, b"\xfd7zXZ\x00", "xz-compressed file"),
    (0, b"QFI\xfb", "QEMU QCOW image"),
    (0, b"<<< Oracle VM VirtualBox Disk Image >>>", "VirtualBox VDI"),
    (64, b"<<< Oracle VM VirtualBox Disk Image >>>", "VirtualBox VDI"),
)

# Extensions an investigator expects to work, by format.
_EXT_FORMAT = {
    ".e01": "E01", ".ex01": "EX01", ".vhdx": "VHDX", ".vhd": "VHD", ".vmdk": "VMDK",
    ".iso": "ISO", ".dd": "RAW", ".raw": "RAW", ".img": "RAW", ".bin": "RAW",
    ".001": "RAW", ".mem": "RAW",
}


@dataclass
class Sniff:
    """What the first bytes of a file say it is."""
    kind: str                   # E01 / EX01 / VHDX / VHD / VMDK / ISO / RAW / UNSUPPORTED / TEXT / EMPTY / UNREADABLE
    detail: str = ""            # e.g. "MBR partition table", the unsupported format's name
    error: str = ""             # why the file could not be read, for UNREADABLE

    @property
    def supported(self) -> bool:
        return self.kind in SUPPORTED


def _read(path: str, offset: int, size: int) -> bytes:
    with open(path, "rb") as fh:
        fh.seek(offset)
        return fh.read(size)


def _looks_like_text(data: bytes) -> bool:
    if not data:
        return False
    sample = data[:4096]
    printable = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b < 127)
    return printable / len(sample) > 0.95


def sniff_format(path: str) -> Sniff:
    """Identify an image by its content, never by its extension."""
    try:
        size = os.path.getsize(path)
        if size == 0:
            return Sniff("EMPTY", "the file is 0 bytes")
        head = _read(path, 0, 65536)
    except PermissionError as exc:
        return Sniff("UNREADABLE", error="PermissionError: %s" % exc)
    except OSError as exc:
        return Sniff("UNREADABLE", error="%s: %s" % (type(exc).__name__, exc))

    if head.startswith(b"EVF\x09\x0d\x0a\xff\x00"):
        return Sniff("E01", "Expert Witness Format (EWF)")
    if head.startswith(b"EVF2\x0d\x0a\x81\x00"):
        return Sniff("EX01", "Expert Witness Format version 2 (Ex01)")
    if head.startswith(b"vhdxfile"):
        return Sniff("VHDX", "Hyper-V virtual disk")
    if head.startswith(b"conectix"):
        return Sniff("VHD", "dynamic Virtual PC / Hyper-V disk")
    if head.startswith(b"KDMV"):
        return Sniff("VMDK", "VMware sparse extent")
    if b"# Disk DescriptorFile" in head[:2048]:
        return Sniff("VMDK", "VMware descriptor")
    for off, sig, name in _UNSUPPORTED_SIGS:
        if head[off:off + len(sig)] == sig:
            return Sniff("UNSUPPORTED", name)
    try:
        if size > 32774 and _read(path, 32769, 5) == b"CD001":
            return Sniff("ISO", "ISO 9660 optical image")
        if size >= 512 and _read(path, size - 512, 8) == b"conectix":
            return Sniff("VHD", "fixed Virtual PC / Hyper-V disk")
    except OSError:
        pass

    if len(head) >= 1024 and head[512:520] == b"EFI PART":
        return Sniff("RAW", "GPT partition table")
    boot = classify_boot_sector(head[:512])
    if boot != "unknown":
        return Sniff("RAW", "a single %s volume" % boot)
    if len(head) >= 512 and head[510:512] == b"\x55\xaa":
        return Sniff("RAW", "MBR partition table")
    if _looks_like_text(head):
        return Sniff("TEXT", "plain text")
    # A raw image with no recognisable start (a split segment that is not the
    # first, a memory dump, a wiped disk) still opens as raw.
    return Sniff("RAW", "no partition table or file system at the start")


# --------------------------------------------------------------------------
# Boot sectors
# --------------------------------------------------------------------------

def classify_boot_sector(data: bytes) -> str:
    """The volume type a boot sector declares (OEM id at offset 3)."""
    if not data or len(data) < 90:
        return "unknown"
    oem = data[3:11]
    if oem == b"-FVE-FS-":
        return "BitLocker"
    if oem == b"NTFS    ":
        return "NTFS"
    if oem == b"EXFAT   ":
        return "exFAT"
    if data[3:7] == b"ReFS" or data[0:4] == b"ReFS":
        return "ReFS"
    if data[82:90] == b"FAT32   ":
        return "FAT32"
    if data[54:62] in (b"FAT16   ", b"FAT12   ", b"FAT     "):
        return "FAT"
    return "unknown"


# --------------------------------------------------------------------------
# Segments
# --------------------------------------------------------------------------

_SEGMENT_PATTERNS = (
    # (regex on the extension, first segment number, digits)
    (re.compile(r"^\.([Ee])(\d{2})$"), 1),       # .E01 .E02
    (re.compile(r"^\.(Ex)(\d{2})$", re.I), 1),   # .Ex01
    (re.compile(r"^\.()(\d{3})$"), 1),           # .001 .002
)


@dataclass
class SegmentReport:
    first: str                                  # the path that should be opened
    segments: List[str] = field(default_factory=list)
    wrong_segment: bool = False                 # a later segment was chosen
    missing: List[int] = field(default_factory=list)


def check_segments(paths: Sequence[str]) -> SegmentReport:
    """Was the first segment chosen, and is every segment present?"""
    paths = [p for p in paths if p]
    if not paths:
        return SegmentReport(first="")
    chosen = sorted(paths)[0]
    directory = os.path.dirname(os.path.abspath(chosen))
    base, ext = os.path.splitext(os.path.basename(chosen))
    for rx, first_no in _SEGMENT_PATTERNS:
        m = rx.match(ext)
        if not m:
            continue
        prefix, digits = m.group(1), m.group(2)
        width = len(digits)
        found = {}
        try:
            names = os.listdir(directory)
        except OSError:
            names = []
        ext_rx = re.compile(r"^%s\.%s(\d{%d})$" % (re.escape(base), re.escape(prefix), width),
                            re.I)
        for name in names:
            mm = ext_rx.match(name)
            if mm:
                found[int(mm.group(1))] = os.path.join(directory, name)
        if not found:
            return SegmentReport(first=chosen, segments=[chosen])
        nums = sorted(found)
        first_path = found.get(first_no)
        wrong = int(digits) != first_no and first_path is not None and len(paths) == 1
        missing = [n for n in range(first_no, nums[-1] + 1) if n not in found]
        return SegmentReport(first=first_path or chosen,
                             segments=[found[n] for n in nums],
                             wrong_segment=wrong or (first_path is None and int(digits) != first_no),
                             missing=missing)
    return SegmentReport(first=chosen, segments=list(paths))


# --------------------------------------------------------------------------
# The whole file
# --------------------------------------------------------------------------

@dataclass
class ImagePreflight:
    paths: List[str]
    sniff: Sniff
    segments: SegmentReport
    size_bytes: int = 0
    issues: List[SessionIssue] = field(default_factory=list)
    # image_integrity.check_image: stored hashes, completeness, segment files.
    integrity: Optional[dict] = None

    @property
    def blocked(self) -> bool:
        """True when nothing can be read: extraction must not start."""
        return any(i.severity == "error" for i in self.issues)

    @property
    def summary(self) -> str:
        n = len(self.segments.segments) or 1
        return "%s%s  |  %s" % (self.sniff.kind,
                                ("  |  %d segments" % n) if n > 1 else "",
                                human_size(self.size_bytes))


def human_size(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


def preflight_image(paths: Sequence[str]) -> ImagePreflight:
    """Read the chosen file(s) and name every problem before anything opens."""
    paths = [os.path.abspath(p) for p in paths if p]
    seg = check_segments(paths)
    target = seg.first or (paths[0] if paths else "")
    issues: List[SessionIssue] = []
    image = os.path.basename(target) if target else ""

    if not target or not os.path.exists(target):
        sniff = Sniff("UNREADABLE", error="file not found")
        issues.append(make_issue("image_unreadable", "The file does not exist: %s" % target,
                                 image=image))
        return ImagePreflight(paths, sniff, seg, 0, issues)
    if os.path.isdir(target):
        sniff = Sniff("UNREADABLE", error="a folder")
        issues.append(make_issue("not_an_image",
                                 "A folder was chosen. To read a folder of collected artifacts "
                                 "use the Offline Importer instead.", image=image))
        return ImagePreflight(paths, sniff, seg, 0, issues)

    sniff = sniff_format(target)
    total = 0
    for p in (seg.segments or [target]):
        try:
            total += os.path.getsize(p)
        except OSError:
            pass

    if seg.wrong_segment:
        issues.append(make_issue("wrong_segment_selected",
                                 "Chosen: %s; open %s instead." % (
                                     os.path.basename(sorted(paths)[0]),
                                     os.path.basename(seg.first)),
                                 image=image))
    if seg.missing:
        issues.append(make_issue("missing_segments",
                                 "Missing segment number(s): %s." % ", ".join(
                                     str(n) for n in seg.missing[:20]),
                                 image=image, segments_found=len(seg.segments)))

    # A VMware disk is opened from its small descriptor, which lists the extents;
    # choosing one of the extents (name-s003.vmdk / -f001 / -flat) skips it.
    m = re.match(r"^(.*)-(?:s|f)\d{3}\.vmdk$|^(.*)-flat\.vmdk$", os.path.basename(target), re.I)
    if m:
        desc = os.path.join(os.path.dirname(target), (m.group(1) or m.group(2)) + ".vmdk")
        if os.path.isfile(desc):
            issues.append(make_issue("wrong_segment_selected",
                                     "A VMware extent was chosen; open its descriptor %s instead."
                                     % os.path.basename(desc), image=image))

    ext = os.path.splitext(target)[1].lower()
    expected = _EXT_FORMAT.get(ext)
    if re.match(r"^\.e\d{2}$", ext):
        expected = "E01"

    if sniff.kind == "UNREADABLE":
        if "permission" in sniff.error.lower() or "being used" in sniff.error.lower():
            issues.append(make_issue("image_locked", sniff.error, image=image))
        else:
            issues.append(make_issue("image_unreadable", sniff.error, image=image))
    elif sniff.kind == "EMPTY":
        issues.append(make_issue("image_corrupted", "The file is empty (0 bytes).", image=image))
    elif sniff.kind == "UNSUPPORTED":
        issues.append(make_issue("unsupported_image_format", "This file is %s." % sniff.detail,
                                 image=image, detected=sniff.detail))
    elif sniff.kind == "TEXT":
        issues.append(make_issue("not_an_image",
                                 "Its content is plain text%s." % (
                                     " although it is named %s" % ext if ext else ""),
                                 image=image))
    elif expected in ("E01", "EX01", "VHDX", "VMDK") and sniff.kind == "RAW":
        # The name promises a container but the header is not one: either a
        # renamed file, or the header itself is damaged.
        issues.append(make_issue("image_corrupted",
                                 "It is named %s but does not start with a %s header - it is "
                                 "damaged, or not really a %s file." % (ext, expected, expected),
                                 image=image, detected=sniff.detail))
    elif expected and expected != sniff.kind and not (
            expected == "RAW" and sniff.kind in SUPPORTED):
        logger.info("%s: named %s but the content is %s (%s); opening it as %s",
                    image, ext, sniff.kind, sniff.detail, sniff.kind)

    integrity = None
    if sniff.kind in ("E01", "EX01") and not any(i.severity == "error" for i in issues):
        # A lone E01 is common (single-segment acquisition) - but whether it
        # holds the whole disk is a question the section headers answer, and
        # so is whether it carries a hash to verify it against. Neither stops
        # the parse: what is present can still be read.
        try:
            from image_integrity import check_image
        except ImportError:
            from .image_integrity import check_image
        try:
            integrity = check_image([target])
            if "image_incomplete" in integrity["problems"] and integrity.get("declared_bytes"):
                issues.append(make_issue(
                    "image_incomplete",
                    "It covers %s of the %s it declares (%.1f%%)." % (
                        human_size(integrity["covered_bytes"]),
                        human_size(integrity["declared_bytes"]),
                        100.0 * (integrity.get("coverage") or 0)),
                    image=image))
            if "image_no_stored_hash" in integrity["problems"]:
                issues.append(make_issue("image_no_stored_hash", image=image))
        except Exception as exc:
            logger.debug("integrity check skipped: %s", exc)
    return ImagePreflight(paths, sniff, seg, total, issues, integrity)


# --------------------------------------------------------------------------
# Partitions
# --------------------------------------------------------------------------

@dataclass
class PartitionFacts:
    label: str
    file_system: str = "Unknown"         # NTFS / FAT32 / ... / Unknown
    boot_kind: str = "unknown"           # classify_boot_sector of its first sector
    has_windows: Optional[bool] = None   # Windows\System32\config present
    verified: bool = True                # False for an invented fallback partition
    selected: bool = True

    @property
    def encrypted(self) -> bool:
        return self.boot_kind == "BitLocker"


def partition_issues(partitions: Iterable[PartitionFacts]) -> List[SessionIssue]:
    parts = list(partitions)
    chosen = [p for p in parts if p.selected]
    issues: List[SessionIssue] = []
    if parts and not chosen:
        issues.append(make_issue("no_partition_selected"))
        return issues
    for p in chosen:
        if p.encrypted:
            issues.append(make_issue("bitlocker_volume", partition=p.label))
        elif p.file_system in ("", "Unknown", "UNKNOWN", None):
            if p.boot_kind not in ("unknown", "", None):
                # The first sector names a file system that then will not open:
                # the volume is there but its structures are not - most often a
                # partial acquisition, or damage.
                detail = ("Its boot sector declares %s, but the file system did not open - "
                          "the image may be incomplete (a partial acquisition) or damaged."
                          % p.boot_kind)
            elif not p.verified:
                detail = ("The partition table could not be read, so the whole image was "
                          "offered as one volume.")
            else:
                detail = ""
            issues.append(make_issue("no_filesystem", detail, partition=p.label))
    readable = [p for p in chosen if not p.encrypted and p.file_system not in
                ("", "Unknown", "UNKNOWN", None)]
    if readable and all(p.has_windows is False for p in readable):
        issues.append(make_issue("no_windows_partition",
                                 partitions=", ".join(p.label for p in readable)))
    return issues


# --------------------------------------------------------------------------
# The case
# --------------------------------------------------------------------------

def _is_inside(child: str, parent: str) -> bool:
    try:
        child, parent = os.path.abspath(child), os.path.abspath(parent)
        return os.path.commonpath([child, parent]) == parent
    except ValueError:      # different drives
        return False


def check_case(case_root: Optional[str], image_paths: Sequence[str] = (),
               needed_bytes: int = 0, reserve_bytes: int = 2 * 1024 ** 3) -> List[SessionIssue]:
    """No case / not writable / image inside it / not enough free space."""
    if not case_root:
        return [make_issue("no_case")]
    issues: List[SessionIssue] = []
    try:
        os.makedirs(case_root, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".crow_write_probe_", dir=case_root)
        os.close(fd)
        os.remove(probe)
    except OSError as exc:
        issues.append(make_issue("case_not_writable", "%s: %s" % (type(exc).__name__, exc),
                                 case=case_root))
        return issues
    for p in image_paths:
        if p and _is_inside(p, case_root):
            issues.append(make_issue("image_inside_case", image=os.path.basename(p),
                                     case=case_root))
            break
    try:
        free = shutil.disk_usage(case_root).free
        want = int(needed_bytes or 0) + reserve_bytes
        if free < want:
            issues.append(make_issue("low_disk_space",
                                     "%s free; about %s may be needed." % (
                                         human_size(free), human_size(want)),
                                     case=case_root))
    except OSError:
        pass
    return issues


# --------------------------------------------------------------------------
# Opening errors
# --------------------------------------------------------------------------

def issue_for_open_error(exc: BaseException, image: str = "") -> SessionIssue:
    """One exception from opening an image -> the issue an investigator can act on."""
    text = "%s: %s" % (type(exc).__name__, exc)
    low = text.lower()
    if isinstance(exc, (ImportError, ModuleNotFoundError)) or "no module named" in low:
        return make_issue("dependency_missing", text, image=image)
    if isinstance(exc, PermissionError) or "being used by another process" in low \
            or "winerror 32" in low or "sharing violation" in low:
        return make_issue("image_locked", text, image=image)
    if "unsupported" in low and "format" in low:
        return make_issue("unsupported_image_format", text, image=image)
    if "segment" in low and ("missing" in low or "not found" in low):
        return make_issue("missing_segments", text, image=image)
    if any(k in low for k in ("corrupt", "checksum", "crc", "truncated", "unexpected end",
                              "invalid header", "bad header", "short read")):
        return make_issue("image_corrupted", text, image=image)
    return make_issue("image_unreadable", text, image=image)
