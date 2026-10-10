"""One python-registry object per hive file for the length of a parse.

``Registry.Registry(path)`` reads the WHOLE hive into memory (its constructor
does ``self._buf = f.read()``). The offline registry parser called it once per
lookup - 70 helper calls, several inside loops, and the ControlSet fallback
re-opened the hive for every path it tried - so a 127 MB SOFTWARE hive was
read from disk over and over: 226 s on case 7.10.2026.

``open_hive(path)`` hands back the same object for the same file while a
``hive_cache()`` block is active on this thread. The key is the absolute path
plus the file's modification time and size, so a hive rewritten in place (a
replayed copy, a re-collection) is read again. Outside a block it is exactly
``Registry.Registry(path)``: callers that do not opt in see no change.

The cache is per thread (two parsers in two threads never share objects) and
bounded by the total size of the files it holds; the least recently used hive
is dropped first.
"""
import contextlib
import os
import threading
from collections import OrderedDict

from Registry import Registry as _Registry

# A parse touches SYSTEM, SOFTWARE, COMPONENTS, the user hives and their
# replayed copies; the largest seen is 127 MB. 768 MB holds a whole machine's
# set without letting a pathological case grow without bound.
MAX_BYTES = 768 * 1024 * 1024

_local = threading.local()


class _Cache:
    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self.items = OrderedDict()          # key -> (reg, size)
        self.size = 0
        self.opened = 0                     # files actually read (for tests / stats)
        self.hits = 0

    def get(self, key):
        hit = self.items.get(key)
        if hit is None:
            return None
        self.items.move_to_end(key)
        self.hits += 1
        return hit[0]

    def put(self, key, reg, size):
        self.items[key] = (reg, size)
        self.size += size
        while self.size > self.max_bytes and len(self.items) > 1:
            _old, (_reg, old_size) = self.items.popitem(last=False)
            self.size -= old_size


def _key(path):
    st = os.stat(path)
    return (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size), st.st_size


def open_hive(path):
    """``Registry.Registry(path)``, read once per parse while a cache is on."""
    cache = getattr(_local, "cache", None)
    if cache is None or not isinstance(path, (str, os.PathLike)):
        return _Registry.Registry(path)
    try:
        key, size = _key(path)
    except OSError:
        return _Registry.Registry(path)
    reg = cache.get(key)
    if reg is None:
        reg = _Registry.Registry(path)
        cache.opened += 1
        cache.put(key, reg, size)
    return reg


@contextlib.contextmanager
def hive_cache(max_bytes=MAX_BYTES):
    """Cache hive objects on this thread until the block ends (re-entrant:
    an inner block reuses the outer cache)."""
    outer = getattr(_local, "cache", None)
    if outer is None:
        _local.cache = _Cache(max_bytes)
    try:
        yield _local.cache
    finally:
        if outer is None:
            _local.cache = None


def active():
    """The cache in effect on this thread, or None."""
    return getattr(_local, "cache", None)
