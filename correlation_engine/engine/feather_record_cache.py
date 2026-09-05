"""Feather work, done once per run instead of once per wing.

The GUI runs a multi-wing pipeline as one `PipelineExecutor` per wing: a new
executor, a new engine, and a fresh read of every feather that wing names. Wings
share feathers heavily — of the eleven shipped Wings, `mft_usn` appears in eight
and `prefetch` in seven — so an eleven-wing run opened, read and re-derived the
same databases up to eleven times. Each pass is a `SELECT *` over every table,
a dict per row, the wing filters, and identity extraction on every surviving
row. That is the lag between wings, and it is also why the feather connections
looked like they were being closed and reopened for every wing: they were.

This cache is **run-scoped**. The GUI worker makes one per run and hands it to
each executor, which forwards it to the engine. Nothing owns it for longer than
a run, so a case parsed again in the same session never sees a stale feather.

    cache = FeatherRecordCache(max_bytes=1024 ** 3)
    key = cache.key(db_path, filter_signature, kind="identity_records")
    hit = cache.get(key)
    if hit is None:
        hit = expensive_load()
        cache.put(key, hit)

**When no cache is provided every caller must behave exactly as before.** The
engines take `feather_cache=None` as "load it again", which is what they did
before this module existed, so the CLI, the tests and any direct caller are
untouched.

Two properties this has to have, and the reasons they are not optional:

* **The key is file identity, not a path.** Path + mtime_ns + size. Pipelines
  with `auto_create_feathers` rewrite a feather between wings, and serving the
  previous contents under the same path would put stale evidence in a later
  wing's findings with nothing anywhere to say so. If the file cannot be
  stat'd, `key()` returns None and the caller loads normally — an unkeyable
  feather is never cached.
* **The filters are part of the key.** Records are cached *after* the wing
  filters ran, so a different filter set is a different result. Filters are
  fixed for a run, so in practice this is one value; it is in the key because a
  future per-wing filter would otherwise silently reuse the wrong rows.

Entries are evicted least-recently-used once the budget is exceeded, and the
eviction is logged: a case too large for the budget degrades to exactly the old
behaviour rather than exhausting memory.
"""

import logging
import os
import sys
from collections import OrderedDict
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 1024 ** 3  # 1 GiB


def file_signature(path) -> Optional[Tuple[str, int, int]]:
    """(absolute path, mtime_ns, size) — or None if the file cannot be stat'd.

    None means "do not cache this": a feather that cannot be identified cannot
    be proven unchanged.
    """
    try:
        resolved = os.path.abspath(str(path))
        stat = os.stat(resolved)
        return (resolved, stat.st_mtime_ns, stat.st_size)
    except Exception:
        return None


def estimate_size(payload) -> int:
    """A cheap, deliberately approximate size for the budget.

    `sys.getsizeof` does not follow references, so a list of dicts of strings
    reports as a few hundred bytes. Walking every value of every row of every
    feather to get an exact figure would cost as much as the work being cached,
    so this samples: full accounting for the first `SAMPLE` rows, then scales.
    The budget is a guard rail, not an allocator.
    """
    SAMPLE = 200
    try:
        if isinstance(payload, (list, tuple)):
            if not payload:
                return 0
            sample = payload[:SAMPLE]
            sampled = sum(_row_size(row) for row in sample)
            return int(sampled * (len(payload) / float(len(sample))))
        return _row_size(payload)
    except Exception:
        return 0


def _row_size(row) -> int:
    try:
        if isinstance(row, dict):
            return sys.getsizeof(row) + sum(
                sys.getsizeof(k) + sys.getsizeof(v)
                for k, v in row.items()
                if not isinstance(v, (list, dict, tuple, set))
            )
        if isinstance(row, (list, tuple)):
            return sys.getsizeof(row) + sum(_row_size(item) for item in row)
        return sys.getsizeof(row)
    except Exception:
        return 0


class FeatherRecordCache:
    """LRU cache of per-feather work, alive for exactly one run."""

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES, label: str = "run"):
        self.max_bytes = int(max_bytes) if max_bytes and max_bytes > 0 else DEFAULT_MAX_BYTES
        self.label = label
        self._entries: "OrderedDict[tuple, Any]" = OrderedDict()
        self._sizes = {}
        self._bytes = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.loads_served = 0

    # -- keys ---------------------------------------------------------------

    @staticmethod
    def key(db_path, filter_signature: Any = None,
            kind: str = "identity_records") -> Optional[tuple]:
        """A cache key, or None when the feather cannot be identified."""
        signature = file_signature(db_path)
        if signature is None:
            return None
        return (kind, signature, repr(filter_signature))

    # -- access -------------------------------------------------------------

    def get(self, key) -> Optional[Any]:
        if key is None:
            return None
        if key in self._entries:
            self._entries.move_to_end(key)
            self.hits += 1
            return self._entries[key]
        self.misses += 1
        return None

    def put(self, key, payload, size_bytes: Optional[int] = None) -> None:
        if key is None or payload is None:
            return
        size = int(size_bytes) if size_bytes is not None else estimate_size(payload)
        if size > self.max_bytes:
            # One feather larger than the whole budget: caching it would evict
            # everything else and then itself. Say so and do not store it.
            logger.info(
                f"[FeatherCache:{self.label}] not caching {key[1][0]!r} "
                f"(~{size / 1e6:.0f} MB exceeds the {self.max_bytes / 1e6:.0f} MB budget)"
            )
            return
        if key in self._entries:
            self._bytes -= self._sizes.get(key, 0)
        self._entries[key] = payload
        self._sizes[key] = size
        self._bytes += size
        self._entries.move_to_end(key)
        self._evict_to_budget()

    def _evict_to_budget(self) -> None:
        while self._bytes > self.max_bytes and self._entries:
            evicted_key, _ = self._entries.popitem(last=False)
            self._bytes -= self._sizes.pop(evicted_key, 0)
            self.evictions += 1
            logger.info(
                f"[FeatherCache:{self.label}] evicted {evicted_key[1][0]!r} to stay "
                f"within the {self.max_bytes / 1e6:.0f} MB budget "
                f"(now ~{self._bytes / 1e6:.0f} MB); the next wing that needs it "
                f"will read it again"
            )

    # -- reporting ----------------------------------------------------------

    def note_load(self) -> None:
        """Record that a caller did the real load. Counted so a test — and the
        run log — can show one load per feather per run rather than one per
        wing, which is the whole point of this class."""
        self.loads_served += 1

    def stats(self) -> dict:
        return {
            'entries': len(self._entries),
            'approx_bytes': self._bytes,
            'hits': self.hits,
            'misses': self.misses,
            'evictions': self.evictions,
            'loads': self.loads_served,
            'max_bytes': self.max_bytes,
        }

    def log_summary(self) -> None:
        stats = self.stats()
        logger.info(
            f"[FeatherCache:{self.label}] {stats['loads']} feather load(s), "
            f"{stats['hits']} reuse(s), {stats['evictions']} eviction(s), "
            f"~{stats['approx_bytes'] / 1e6:.0f} MB held"
        )
