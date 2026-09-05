r"""Walk a hive's allocator rather than its tree.

Every tool that reads a registry walks the TREE: start at the root, follow
subkey lists down, report what you reach. That misses three things this module
exists to recover, all of them documented in the Eye-describe article "The
Windows Registry, End to End".

**Deleted keys and values.** Deleting a key does not erase it. Windows flips the
cell's size field from negative to positive, marks it free, and moves on - the
signature, the name, the timestamp and the pointers are all still there until
something allocates over that space. A key unlinked from the tree is invisible
to every tree walker and is still in the file. Measured on the hives this was
written against: 1,451 keys and 6,347 values sat in free space in SOFTWARE
alone.

**Class names.** An nk record can carry a class name, a second string separate
from the key's name and stored in its own cell. Most keys have none, and the
field is where the four keys under Control\Lsa keep the machine's boot key -
data in a place most registry viewers do not render at all.

**Security descriptors.** Keys do not get one each; identical descriptors are
stored once and shared, each carrying a count of how many keys use it. A key
with a descriptor of its own, whose siblings share one, has had its permissions
changed - and that is visible structurally, without reading a single ACL.

One pass collects all three, which is why they live together here. Walking the
allocator is also far cheaper than walking the tree: SOFTWARE holds 392,966
keys, and the cell walk over every hive of a machine finishes in seconds.

Nothing here modifies a hive. It reads.
"""

import datetime
import logging
import os
import bisect
import struct

logger = logging.getLogger(__name__)

try:
    from Registry import Registry
    from Registry import RegistryParse
    REGISTRY_AVAILABLE = True
except ImportError:                                     # pragma: no cover
    Registry = None
    RegistryParse = None
    REGISTRY_AVAILABLE = False

# A primary hive's base block occupies the first 4096 bytes; hive bins
# follow. Every offset stored inside a record is relative to the first
# bin, so this is what turns one into a file offset.
PRIMARY_BASE_BLOCK_LEN = 4096

# A cell's data begins 4 bytes after the cell, past its size field.
_CELL_DATA = 4

# Offsets inside an nk record, from the start of its data.
_NK_TIMESTAMP = 0x04
_NK_SUBKEY_COUNT = 0x14
_NK_VALUE_COUNT = 0x24
_NK_NAME_LENGTH = 0x48
_NK_NAME = 0x4C

# Offsets inside a vk record, from the start of its data. Verified against a
# value python-registry decodes, rather than from memory: these were all four
# bytes too high, which is not an error a parser reports. Every carved value
# came back with the wrong size, the wrong type and data read from the wrong
# place, and every one of them looked plausible.
#
#   0x00  "vk"          0x08  data offset
#   0x02  name length   0x0C  data type
#   0x04  data size     0x10  flags
_VK_NAME_LENGTH = 0x02
_VK_DATA_SIZE = 0x04
_VK_DATA_OFFSET = 0x08
_VK_DATA_TYPE = 0x0C
_VK_NAME = 0x14

# The high bit of a vk data size means the data IS the offset field.
_VK_INLINE = 0x80000000

# Offsets inside an sk record, from the start of its data.
_SK_REFERENCE_COUNT = 0x0C
_SK_DESCRIPTOR_SIZE = 0x10
_SK_DESCRIPTOR = 0x14

# A name longer than this is not a name; it is a misread offset. Registry key
# names are bounded by 255 characters in practice, and a freed cell's bytes can
# say anything at all.
_MAX_NAME = 512

# Offsets inside an nk record that carving needs beyond the ones above.
_NK_PARENT = 0x10
_NK_CLASSNAME_OFFSET = 0x30
_NK_VALUE_LIST = 0x28

# The base block's reorganisation timestamp. Compacting a hive rewrites its
# free space, so a hive reorganised recently holds less recoverable history -
# worth knowing before anyone spends an afternoon carving it.
_REGF_REORGANIZED = 0xA8

# "Free does not mean intact." A freed cell can be partly overwritten while its
# first two bytes still read nk or vk, so every field is checked before it is
# believed. These bounds are what "believed" means here.
#
# A registry timestamp outside this range is not a timestamp; it is whatever
# was written over one. The guide's example is a key dated the year 30,000.
_MIN_YEAR = 1990
_MAX_YEAR = 2100

# A key with more than this many values or subkeys is a misread count, not a
# key. The largest real keys on a Windows install are in the low thousands.
_MAX_COUNT = 65536

# A carved value larger than this is not read. The data is recovered to say
# what the value held, not to reconstitute a file out of free space.
_MAX_CARVED_DATA = 4096

# How far a parent chain is followed before it is treated as a loop. A freed
# cell can point anywhere, including at itself.
_MAX_PARENT_DEPTH = 32


def _text(raw, at, length):
    """A record's name, ASCII or UTF-16 depending on the record's flag.

    Freed cells hold whatever was there before, so this never raises: an
    undecodable name is a name that could not be read, not a reason to abandon
    the walk.
    """
    if length <= 0 or length > _MAX_NAME or at + length > len(raw):
        return ""
    try:
        return raw[at:at + length].decode("latin-1", "replace")
    except Exception:
        return ""


class HiveWalk(object):
    """What one pass over a hive's allocator found."""

    def __init__(self, hive_path):
        self.hive_path = hive_path
        self.bins = 0
        self.cells_allocated = 0
        self.cells_free = 0
        self.free_bytes = 0
        self.class_names = []          # allocated keys carrying a class name
        self.security = []             # one entry per distinct sk record
        self.carved_keys = []          # nk records sitting in free space
        self.carved_values = []        # vk records sitting in free space
        self.error = ""
        # Compacting a hive rewrites its free space, so this says how
        # much recoverable history the hive still holds.
        self.reorganized_raw = None

    def __repr__(self):
        return ("<HiveWalk %s bins=%d free=%d carved_keys=%d carved_values=%d "
                "classes=%d sk=%d>"
                % (self.hive_path, self.bins, self.cells_free,
                   len(self.carved_keys), len(self.carved_values),
                   len(self.class_names), len(self.security)))


def walk_hive(hive_path, want_paths=True):
    """One pass over every cell in `hive_path`.

    `want_paths` resolves the full key path for allocated records carrying a
    class name or a security descriptor. It costs a parent-chain walk per hit,
    which is cheap because the hits are rare - about a thousand keys in a
    SOFTWARE hive of nearly four hundred thousand.

    Returns a HiveWalk. Never raises: a hive that cannot be opened comes back
    with `error` set and empty lists, because a parser that cannot carve must
    still parse.
    """
    result = HiveWalk(hive_path)
    if not REGISTRY_AVAILABLE:
        result.error = "python-registry is not available"
        return result

    try:
        reg = Registry.Registry(hive_path)
        with open(hive_path, "rb") as handle:
            raw = handle.read()
    except Exception as exc:
        result.error = "cannot read hive: %s" % exc
        logger.debug("hive walk could not open %s: %s", hive_path, exc)
        return result

    seen_sk = {}
    # Every live key, by cell offset: (name, is_root, parent_offset). Built as
    # the walk goes and used afterwards to give carved keys their path, because
    # a carved key's parent may sit in a bin this pass has not reached yet.
    allocated = {}

    try:
        for hbin in reg._regf.hbins():
            result.bins += 1
            try:
                cells = hbin.cells()
            except Exception:
                continue
            for cell in cells:
                try:
                    offset = cell.offset()
                    free = cell.is_free()
                except Exception:
                    continue

                if free:
                    result.cells_free += 1
                    try:
                        result.free_bytes += abs(cell.size())
                    except Exception:
                        pass
                    _carve(raw, offset, result)
                else:
                    result.cells_allocated += 1
                    _note_allocated_key(raw, offset, allocated)
                    _allocated(raw, offset, cell, result, seen_sk, want_paths)
    except Exception as exc:
        result.error = "walk stopped early: %s" % exc
        logger.debug("hive walk stopped on %s: %s", hive_path, exc)

    _resolve_carved_paths(raw, result, allocated)
    result.reorganized_raw = _read_reorganized(raw)
    return result


def _read_reorganized(raw):
    """The base block's reorganisation timestamp, or None.

    Compacting a hive rewrites its free space, so this says how much history a
    hive still holds before anyone spends an afternoon carving it. Zero on a
    hive that has never been reorganised, which is not the same as unknown.
    """
    try:
        if len(raw) < _REGF_REORGANIZED + 8:
            return None
        return _sane_timestamp(
            struct.unpack_from("<Q", raw, _REGF_REORGANIZED)[0])
    except Exception:
        return None


def _resolve_carved_paths(raw, result, allocated):
    """Give each carved key its path, where the chain to a live key survives.

    "Its parent is a pointer, not a path." A recovered nk holds its parent's
    OFFSET, and that cell may itself have been freed and reused. Where the
    chain breaks the path is unknown, and this records it as unknown - because
    inventing one is how a carved artefact becomes a wrong conclusion.

    Measured on a reference SOFTWARE hive: 941 of 1,451 carved keys reach a
    live parent. The other 510 keep their name, their date and their values,
    and no path at all.
    """
    for carved in result.carved_keys:
        path, resolved = _path_from_parent(
            raw, carved.get("parent_offset", 0), allocated)
        if resolved:
            carved["key_path"] = path + "\\" + carved["key_name"] if path else carved["key_name"]
            carved["parent_resolved"] = True
        else:
            # Left empty on purpose. A partial path reads like a real one.
            carved["key_path"] = ""
            carved["parent_resolved"] = False

        for value in carved.get("values", []):
            value["key_path"] = carved["key_path"]
            value["parent_cell_offset"] = carved["cell_offset"]


def _path_from_parent(raw, parent_offset, allocated):
    """(path, True) when every link up to the root is a live key, else ('', False)."""
    parts = []
    seen = set()
    offset = parent_offset
    for _ in range(_MAX_PARENT_DEPTH):
        if offset in (0, 0xFFFFFFFF):
            return "", False
        cell = PRIMARY_BASE_BLOCK_LEN + offset
        if cell in seen:
            # A freed cell can point at itself, or into a ring.
            return "", False
        seen.add(cell)

        entry = allocated.get(cell)
        if entry is None:
            # The parent is not a live key: either it was freed too, or the
            # offset is not an offset any more.
            return "", False
        name, is_root, next_offset = entry
        if is_root:
            return "\\".join(reversed(parts)), True
        parts.append(name)
        offset = next_offset
    return "", False


def _note_allocated_key(raw, offset, allocated):
    """Record a live key's name and parent, for resolving carved paths later.

    Read straight from the bytes rather than through a RegistryKey, because
    this runs for every allocated cell in the hive - about two million in a
    SOFTWARE hive - and constructing an object per cell to read two fields is
    the difference between seconds and minutes.
    """
    at = offset + _CELL_DATA
    if at + _NK_NAME > len(raw) or raw[at:at + 2] != b"nk":
        return
    try:
        length = struct.unpack_from("<H", raw, at + _NK_NAME_LENGTH)[0]
        name = _text(raw, at + _NK_NAME, length)
        if not name:
            return
        flags = struct.unpack_from("<H", raw, at + 2)[0]
        # 0x0004 marks the root key, which is where a parent chain ends.
        allocated[offset] = (
            name,
            bool(flags & 0x0004),
            struct.unpack_from("<I", raw, at + _NK_PARENT)[0],
        )
    except Exception:
        return


def _sane_timestamp(raw_value):
    """The FILETIME if it could be one, else None.

    A freed cell's timestamp field may be part of something else entirely. The
    guide's example is a key dated the year 30,000, which a parser that trusts
    the field will happily write into a timeline.
    """
    if not raw_value:
        return None
    try:
        moment = (datetime.datetime(1601, 1, 1)
                  + datetime.timedelta(microseconds=raw_value // 10))
    except (OverflowError, ValueError):
        return None
    if not (_MIN_YEAR <= moment.year <= _MAX_YEAR):
        return None
    return raw_value


def _sane_count(value):
    """A count is believed only if a cell could actually address that many."""
    return value if 0 <= value <= _MAX_COUNT else 0


def _read_value(raw, cell_offset):
    """One vk record, with its data, or None if it does not hold together."""
    at = cell_offset + _CELL_DATA
    if at + 24 > len(raw) or raw[at:at + 2] != b"vk":
        return None
    try:
        name_length = struct.unpack_from("<H", raw, at + _VK_NAME_LENGTH)[0]
        # An unnamed value is the key's default value and is legitimate, so a
        # zero-length name is kept rather than discarded.
        name = _text(raw, at + _VK_NAME, name_length) if name_length else "(Default)"
        if name_length and not name:
            return None

        size_field = struct.unpack_from("<I", raw, at + _VK_DATA_SIZE)[0]
        data_offset = struct.unpack_from("<I", raw, at + _VK_DATA_OFFSET)[0]
        inline = bool(size_field & _VK_INLINE)
        size = size_field & 0x7FFFFFFF

        data = None
        if inline and size <= 4:
            # The high bit means the data IS the offset field. Reading the
            # field as a pointer instead is how a four-byte value becomes a
            # wild read somewhere else in the hive.
            data = struct.pack("<I", data_offset)[:size]
        elif 0 < size <= _MAX_CARVED_DATA:
            start = PRIMARY_BASE_BLOCK_LEN + data_offset + _CELL_DATA
            if 0 < start and start + size <= len(raw):
                data = raw[start:start + size]

        return {
            "cell_offset": cell_offset,
            "value_name": name,
            "value_type": struct.unpack_from("<I", raw, at + _VK_DATA_TYPE)[0],
            "data_size": size,
            "inline": inline,
            "data": data,
        }
    except Exception:
        return None


def _carve(raw, offset, result):
    """A freed cell that still holds a recognisable record.

    Nothing here is believed because its signature matched. Every field is
    range-checked first, because part of a record can be overwritten while its
    first two bytes survive - which is the difference between recovering a
    deleted key and reporting somebody else's bytes as one.
    """
    at = offset + _CELL_DATA
    if at + 8 > len(raw):
        return
    signature = raw[at:at + 2]

    if signature == b"nk":
        try:
            length = struct.unpack_from("<H", raw, at + _NK_NAME_LENGTH)[0]
            name = _text(raw, at + _NK_NAME, length)
            if not name:
                return

            value_count = _sane_count(
                struct.unpack_from("<I", raw, at + _NK_VALUE_COUNT)[0])
            value_list = struct.unpack_from("<I", raw, at + _NK_VALUE_LIST)[0]

            # The values this key held, read through its own value list. A
            # deleted key with no values recovered is a name and a date; with
            # them it is what the key actually said.
            values = []
            if value_count and value_list not in (0, 0xFFFFFFFF):
                list_at = PRIMARY_BASE_BLOCK_LEN + value_list + _CELL_DATA
                for index in range(min(value_count, 512)):
                    entry = list_at + 4 * index
                    if entry + 4 > len(raw):
                        break
                    try:
                        target = PRIMARY_BASE_BLOCK_LEN + struct.unpack_from(
                            "<I", raw, entry)[0]
                    except Exception:
                        break
                    value = _read_value(raw, target)
                    if value:
                        values.append(value)

            result.carved_keys.append({
                "cell_offset": offset,
                "key_name": name,
                # Kept raw; the caller formats it. None means the field did not
                # hold a plausible date, and an empty column is the honest
                # rendering of that.
                "timestamp_raw": _sane_timestamp(
                    struct.unpack_from("<Q", raw, at + _NK_TIMESTAMP)[0]),
                "subkey_count": _sane_count(
                    struct.unpack_from("<I", raw, at + _NK_SUBKEY_COUNT)[0]),
                "value_count": value_count,
                # Resolved after the walk: a parent may sit in a bin this pass
                # has not reached yet.
                "parent_offset": struct.unpack_from("<I", raw, at + _NK_PARENT)[0],
                "key_path": "",
                "parent_resolved": False,
                "values": values,
            })
        except Exception:
            return

    elif signature == b"vk":
        # A freed vk reached on its own, without the key that owned it. Kept,
        # because the value is evidence either way, but it carries no path: the
        # key that would give it one is gone.
        value = _read_value(raw, offset)
        if value:
            result.carved_values.append(value)


def _allocated(raw, offset, cell, result, seen_sk, want_paths):
    """A live cell: collect its class name, and its security descriptor once."""
    at = offset + _CELL_DATA
    if at + 8 > len(raw) or raw[at:at + 2] != b"nk":
        return

    try:
        record = cell.child()
    except Exception:
        return
    if not isinstance(record, RegistryParse.NKRecord):
        return

    # ---- class name -------------------------------------------------------
    try:
        if record.has_classname():
            classname = record.classname()
            if classname:
                result.class_names.append({
                    "key_path": _path_of(record) if want_paths else "",
                    "key_name": record.name(),
                    "class_name": classname,
                    "class_length": len(classname),
                    "timestamp": record.timestamp(),
                })
    except Exception:
        pass

    # ---- security descriptor, once per distinct sk record -----------------
    try:
        sk = record.sk_record()
    except Exception:
        return
    if sk is None:
        return
    try:
        sk_offset = sk.offset()
    except Exception:
        return
    if sk_offset in seen_sk:
        return
    seen_sk[sk_offset] = True

    try:
        reference_count = struct.unpack_from("<I", raw, sk_offset + _SK_REFERENCE_COUNT)[0]
        size = struct.unpack_from("<I", raw, sk_offset + _SK_DESCRIPTOR_SIZE)[0]
        if size <= 0 or sk_offset + _SK_DESCRIPTOR + size > len(raw):
            return
        result.security.append({
            "sk_offset": sk_offset,
            "reference_count": reference_count,
            "descriptor": raw[sk_offset + _SK_DESCRIPTOR:sk_offset + _SK_DESCRIPTOR + size],
            "sample_key_path": _path_of(record) if want_paths else "",
        })
    except Exception:
        return


def _path_of(record):
    """The record's full path, or its name if the parent chain cannot be walked.

    A path is a convenience, not the evidence, so a broken parent chain must not
    cost the row that carries it.
    """
    try:
        return record.path()
    except Exception:
        try:
            return record.name()
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Naming a byte offset
# ---------------------------------------------------------------------------
# The transaction logs say which bytes a change touched (see
# registry_transaction_log.changed_spans). An offset is not evidence until it
# has a name, and this is what turns one into the other: every allocated value
# in the hive, indexed by the cell it occupies and by the cell holding its data,
# with the key that owns it.
#
# Both indexes are needed. Changing a value's DATA usually rewrites the data
# cell and leaves the vk record alone, so an index of vk cells only would miss
# exactly the case this exists for.

_INDEX_CACHE = {}


def reset_index_cache():
    """Forget the memoised indexes. For tests, and between cases in one run."""
    _INDEX_CACHE.clear()


def value_index(hive_path):
    """Every allocated value by cell offset, with the key that owns it.

    Memoised per path. Both value_changes() and key_times() need this, and a
    SOFTWARE hive holds nearly four hundred thousand keys - walking it twice
    per parse is a cost with nothing to show for it.

    Returns (index, keys) where index maps an absolute hive offset to a dict of
    key_path, name, type and data, and `keys` maps a key's cell offset to its
    path and last-written time.

    Never raises. An index that cannot be built comes back empty, and the
    caller reports offsets without names rather than nothing at all.
    """
    cached = _INDEX_CACHE.get(hive_path)
    if cached is not None:
        return cached

    index, keys = {}, {}
    if not REGISTRY_AVAILABLE:
        return index, keys

    try:
        reg = Registry.Registry(hive_path)
        with open(hive_path, "rb") as handle:
            raw = handle.read()
    except Exception as exc:
        logger.debug("value_index could not open %s: %s", hive_path, exc)
        return index, keys

    def walk(key, path):
        # python-registry reports the offset of the RECORD; every helper here
        # takes the offset of the CELL, which begins four bytes earlier at the
        # size field. Subtracting the base block length instead - which is the
        # arithmetic that applies to an offset stored INSIDE a record - lands
        # far away and silently indexes nothing at all.
        try:
            offset = key._nkrecord.offset() - _CELL_DATA
        except Exception:
            offset = None
        if offset is not None:
            keys[offset] = {"key_path": path, "timestamp_raw": None}
            try:
                at = offset + _CELL_DATA
                keys[offset]["timestamp_raw"] = _sane_timestamp(
                    struct.unpack_from("<Q", raw, at + _NK_TIMESTAMP)[0])
            except Exception:
                pass

        try:
            values = list(key.values())
        except Exception:
            values = []
        for value in values:
            try:
                vk_offset = value._vkrecord.offset() - _CELL_DATA
            except Exception:
                continue
            record = _read_value(raw, vk_offset)
            if not record:
                continue
            record["key_path"] = path
            record["key_offset"] = offset
            index[vk_offset] = record
            # The data cell too. Changing a value's contents usually rewrites
            # only the cell the record points at and leaves the record itself
            # untouched, so an index of vk cells alone would miss precisely the
            # case this exists for.
            try:
                at = vk_offset + _CELL_DATA
                size_field = struct.unpack_from("<I", raw, at + _VK_DATA_SIZE)[0]
                if not (size_field & _VK_INLINE):
                    data_offset = struct.unpack_from(
                        "<I", raw, at + _VK_DATA_OFFSET)[0]
                    cell = PRIMARY_BASE_BLOCK_LEN + data_offset
                    if PRIMARY_BASE_BLOCK_LEN < cell < len(raw):
                        index[cell] = record
            except Exception:
                pass

        try:
            subkeys = list(key.subkeys())
        except Exception:
            subkeys = []
        for sub in subkeys:
            try:
                walk(sub, path + "\\" + sub.name() if path else sub.name())
            except Exception:
                continue

    try:
        root = reg.root()
        walk(root, root.name())
    except Exception as exc:
        logger.debug("value_index walk failed on %s: %s", hive_path, exc)

    _INDEX_CACHE[hive_path] = (index, keys)
    return index, keys


def sorted_index(index):
    """The index's offsets, sorted once, for name_offset to bisect.

    Built separately because the caller resolves tens of thousands of spans
    against the same index: scanning it per span is O(n) each time and turns a
    two-second pass into an afternoon.
    """
    return sorted(index)


def name_offset(index, keys, offset, order=None, length=1):
    """The value a changed span falls inside, or None.

    Cells are variable length, so this cannot be a dictionary lookup on the
    exact offset - a span usually starts partway into a record. It finds the
    nearest indexed cell at or before the span and accepts it only if the span
    really does fall inside that record's own extent, so a span in unindexed
    space comes back unnamed instead of being attributed to whatever happened
    to precede it.
    """
    if not index:
        return None
    if order is None:
        order = sorted_index(index)
    position = bisect.bisect_right(order, offset) - 1
    if position < 0:
        return None
    start = order[position]
    record = index[start]
    # The record's own extent: the 24-byte vk header, its name, and its data
    # if that data sits in this cell. A span further out than that belongs to
    # something not in the index and is reported unnamed, rather than being
    # attributed to whichever record happened to precede it.
    extent = 24 + len(record.get("value_name") or "") + max(
        record.get("data_size") or 0, 0)
    if offset - start > max(extent, 64):
        return None
    return record


def value_changes(hive_path, log_paths=None, limit=None):
    """Which values the pending transactions changed, and to what.

    This is the join: registry_transaction_log.changed_spans says WHICH BYTES a
    transaction changed, value_index says WHICH VALUE lives at a byte, and the
    hive and the log hold that value before and after.

    It exists because a key records when it was last written and its values
    record nothing at all, so "this key changed" is normally as far as anyone
    can get. The logs get further.

    Two things it is not, both of which must survive to the screen:

      * Not full history. Only transactions still in .LOG1 and .LOG2 - recent
        activity, and a window whose length nobody controls.

      * Not a claim about every change. A span in space the index does not
        cover is reported unnamed rather than attributed to a neighbouring
        record. On the hives this was written against, 87% of spans resolve.

    Returns a list of dicts, oldest transaction first. Never raises.
    """
    try:
        import registry_transaction_log as _log
    except ImportError:                                 # pragma: no cover
        from . import registry_transaction_log as _log

    try:
        entries = _log.changed_spans(hive_path, log_paths)
    except Exception as exc:
        logger.debug("value_changes could not read logs for %s: %s",
                     hive_path, exc)
        return []
    if not entries:
        return []

    index, keys = value_index(hive_path)
    order = sorted_index(index)

    seen = {}
    out = []
    for entry in entries:
        after_image = entry.get("pages") or []
        for offset, before, after in entry["spans"]:
            record = name_offset(index, keys, offset, order)
            if record is None:
                # Nothing live at this offset in the hive. That is exactly what
                # a value being CREATED looks like from here, so before giving
                # up, read the record out of the page that created it. Skipping
                # this step reports zero creations on every machine and never
                # says why - which is what the first version of this did.
                record = _record_from_pages(after_image, offset)
                if record is None:
                    continue
                record["created"] = True
            identity = (entry["sequence"], record.get("key_path"),
                        record.get("value_name"))
            if identity in seen:
                # One value can change in several spans within a transaction -
                # its record and its data cell are not adjacent. That is one
                # change, not several.
                existing = seen[identity]
                existing["span_count"] += 1
                # A span that lands on the cell's size field says the value was
                # created or deleted, which is a stronger and different finding
                # than "its data moved". Whichever span happens to be visited
                # first must not decide that: the first pass reported 390
                # deletions and no creations at all, because a data span for the
                # same value in the same transaction got there first.
                kind = _change_kind(offset, record, before, after)
                if kind != "modified":
                    existing["change_kind"] = kind
                continue
            key_meta = keys.get(record.get("key_offset")) or {}
            row = {
                "sequence": entry["sequence"],
                "change_kind": ("created" if record.get("created")
                                else _change_kind(offset, record, before, after)),
                "hive": os.path.basename(hive_path),
                "key_path": record.get("key_path") or "",
                "value_name": record.get("value_name") or "",
                "value_type": record.get("value_type"),
                # The bytes that DIFFER, which is usually part of the value and
                # not all of it. Named for what they are: calling a partial
                # diff "the old value" would be a wrong answer that reads like
                # a right one, which is the failure this whole page warns about.
                "changed_before": _preview(before),
                "changed_after": _preview(after),
                "changed_bytes": len(after),
                # Exact, and only where the transaction's own pages carry the
                # owning key's new timestamp. Absent for a created value, whose
                # key is not resolvable from a page alone.
                "changed_at_raw": _key_time_from_pages(
                    after_image, record.get("key_offset"),
                    key_meta.get("timestamp_raw")),
                # The complete value as the hive holds it, which is its state
                # BEFORE these pending transactions are applied.
                "value_before": _preview(record.get("data") or b""),
                "offset": offset,
                "span_count": 1,
                "key_last_write_raw": key_meta.get("timestamp_raw"),
            }
            seen[identity] = row
            out.append(row)
            if limit and len(out) >= limit:
                return out
    return out


_PREVIEW_BYTES = 48


def _preview(chunk):
    """A changed span rendered for a person, without pretending to be text.

    Registry data is bytes and most of it is not a string. Rendering it as one
    would put replacement characters in a column an analyst has to compare, so
    printable runs are shown as text and everything else stays hex.
    """
    if not chunk:
        return ""
    clipped = chunk[:_PREVIEW_BYTES]
    try:
        wide = clipped.decode("utf-16-le")
        if wide and all(c.isprintable() or c == "\x00" for c in wide):
            text = wide.replace("\x00", "").strip()
            if text:
                return text if len(chunk) <= _PREVIEW_BYTES else text + " ..."
    except Exception:
        pass
    if all(32 <= b <= 126 for b in clipped):
        text = clipped.decode("latin-1")
        return text if len(chunk) <= _PREVIEW_BYTES else text + " ..."
    hexed = " ".join("%02X" % b for b in clipped)
    return hexed if len(chunk) <= _PREVIEW_BYTES else hexed + " ..."


def _change_kind(offset, record, before, after):
    """created, deleted or modified, from the cell's own size field.

    A cell's size is negative while it is in use and positive once it is freed,
    so a span that lands on the size field is not a data change at all - it is
    the value coming into existence or going out of it. Reporting that as
    "modified" would describe a newly planted Run value as an edit to one that
    was already there, which is a materially different finding.
    """
    cell = record.get("cell_offset")
    if cell is None or offset != cell or len(before) < 4 or len(after) < 4:
        return "modified"
    try:
        was = struct.unpack_from("<i", before, 0)[0]
        now = struct.unpack_from("<i", after, 0)[0]
    except Exception:
        return "modified"
    if was >= 0 and now < 0:
        return "created"
    if was < 0 and now >= 0:
        return "deleted"
    return "modified"


def _record_from_pages(pages, offset):
    """A vk record read out of a transaction's own page, not out of the hive.

    Used only when the hive has nothing live at that offset, which is the
    signature of a value the transaction created. The key it belongs to cannot
    be resolved this way - the page holds the record, not the tree above it -
    so the path is left empty rather than guessed. An empty path is a true
    statement; a guessed one is how a recovered artefact becomes a wrong
    conclusion.
    """
    for page_offset, data in pages or []:
        if not (page_offset <= offset < page_offset + len(data)):
            continue
        at = offset - page_offset
        record = _read_value(data, at)
        if not record:
            return None
        record["cell_offset"] = offset
        record["key_path"] = ""
        record["key_offset"] = None
        # The data lives at a hive offset this page does not contain, so the
        # value's contents are not recoverable from here. The name and the
        # type are, and they are the part that matters for a created value.
        record["data"] = None
        return record
    return None


def _key_time_from_pages(pages, key_offset, hive_time):
    """The owning key's last-write time AFTER the transaction, or None.

    A log entry carries a sequence number and no clock, so "changed in
    transaction 366309" is an ordering and not a time. The pages, though, hold
    the nk records as they stood once the transaction was applied - and writing
    a value updates its key's timestamp, so the key's post-transaction time IS
    the moment that change happened.

    `hive_time` is the same key's timestamp in the hive, and the reason this
    takes it: a dirty page is 4096 bytes and most of it did not change, so a
    key whose nk merely SITS on a dirty page reads back exactly what the hive
    already said. Returning that would label the bound as an exact time - the
    precise false precision this whole change exists to remove. A time is only
    returned when the page genuinely disagrees with the hive, which is what it
    means for this transaction to have touched this key.
    """
    if key_offset is None:
        return None
    for page_offset, data in pages or []:
        if not (page_offset <= key_offset < page_offset + len(data)):
            continue
        at = key_offset - page_offset + _CELL_DATA
        if at + 8 > len(data) or data[at:at + 2] != b"nk":
            return None
        try:
            found = _sane_timestamp(
                struct.unpack_from("<Q", data, at + _NK_TIMESTAMP)[0])
        except Exception:
            return None
        if found is None or found == hive_time:
            return None
        return found
    return None


def key_times(hive_path):
    """Every key in the hive by path, with its last-write time.

    The key-level surface. On a value row a key's timestamp is only ever an
    upper bound - writing any value updates its key, so no value can be newer
    than its key, and at most one value matches it. Here the same number is
    unambiguous, because the row IS the key.
    """
    _, keys = value_index(hive_path)
    out = []
    for offset, meta in keys.items():
        out.append({
            "cell_offset": offset,
            "key_path": meta.get("key_path") or "",
            "timestamp_raw": meta.get("timestamp_raw"),
        })
    return out
