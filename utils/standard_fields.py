"""
Standard Fields Registry — single source of truth for field name synonyms.

The Crow-Eye codebase historically duplicated field-name lists across the
correlation engine (CORE_IDENTITY_FIELDS, _TIMESTAMP_FIELDS), GUI viewers
(_RAW_NAME_FIELDS, _RAW_PATH_FIELDS), and the identity-semantic phase
aggregator. Each duplicate had to be updated by hand when a new parser
introduced a new column name; many drifted out of sync, causing dropped
evidence and silent identity-extraction failures.

This module exposes the canonical synonym registry that lives in
``config/standard_fields/*.json`` and is therefore editable without code
changes when a new parser adds a column.

JSON layout
-----------
Each ``standard_fields/<category>.json`` file is a dict of
``{semantic_name: [synonym, synonym, ...]}``. For example,
``timestamps.json`` contains keys ``timestamp / createdtime /
modifiedtime / accessedtime``.

Usage
-----
::

    from utils.standard_fields import StandardFields

    # All timestamp synonyms, real activity first, parser bookkeeping last
    ts_fields = StandardFields.all_timestamp_fields()

    # All identity-like field synonyms (names first, then paths)
    id_fields = StandardFields.all_identity_fields()

    # Direct access to one category
    creation = StandardFields.category('timestamps', 'createdtime')
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _resolve_registry_dir() -> Path:
    """Return the absolute path to config/standard_fields/."""
    # Path resolution mirrors the working pattern used by
    # correlation_engine/config/semantic_mapping.py:207-211 — first try
    # PathUtils (Crow-Eye-aware app root), fall back to relative.
    try:
        from utils.path_utils import PathUtils  # type: ignore

        app_root = Path(PathUtils.get_app_root())
        candidate = app_root / "config" / "standard_fields"
        if candidate.exists():
            return candidate
    except Exception:
        pass

    # Fallback: this file lives at <root>/utils/standard_fields.py
    candidate = Path(__file__).resolve().parent.parent / "config" / "standard_fields"
    return candidate


class StandardFields:
    """Lazy-loaded, cached access to ``config/standard_fields/*.json``.

    Thread-safe by virtue of immutability after first load. Cache is a
    plain dict; reads are atomic for the small file set involved.
    """

    # File stem → semantic_name → tuple(synonyms). Populated lazily by _load.
    _cache: Dict[str, Dict[str, Tuple[str, ...]]] = {}

    # Real-activity timestamp categories that name "when something
    # happened", not "when we ingested it". Used to order
    # all_timestamp_fields() so engine timestamp extraction prefers real
    # event times over parser bookkeeping (parsed_at / inserted_at).
    _REAL_TIMESTAMP_CATEGORIES = ("timestamp", "modifiedtime", "createdtime", "accessedtime")

    # Categories whose every member is parser bookkeeping. Forced to the
    # very back of all_timestamp_fields() so they only win when no real
    # timestamp exists on the record.
    _BOOKKEEPING_CATEGORIES = ("bookkeeping",)

    # Parser-bookkeeping suffixes — caught even when the synonym landed
    # in a real-activity category.
    _BOOKKEEPING_SUFFIXES = ("parsed_at", "inserted_at", "created_at", "_at")

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #
    @classmethod
    def _load(cls, stem: str) -> Dict[str, Tuple[str, ...]]:
        """Load and cache one JSON file by stem (e.g. ``"timestamps"``)."""
        if stem in cls._cache:
            return cls._cache[stem]

        path = _resolve_registry_dir() / f"{stem}.json"
        if not path.exists():
            logger.warning("standard_fields registry missing: %s", path)
            cls._cache[stem] = {}
            return cls._cache[stem]

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error("standard_fields parse error for %s: %s", path, e)
            cls._cache[stem] = {}
            return cls._cache[stem]

        # Normalize each category's synonym list to an ordered tuple,
        # de-duplicated while preserving JSON order.
        normalized: Dict[str, Tuple[str, ...]] = {}
        for category, synonyms in raw.items():
            if not isinstance(synonyms, list):
                continue
            seen = set()
            out: List[str] = []
            for syn in synonyms:
                if not isinstance(syn, str):
                    continue
                if syn in seen:
                    continue
                seen.add(syn)
                out.append(syn)
            normalized[category] = tuple(out)

        cls._cache[stem] = normalized
        return normalized

    # ------------------------------------------------------------------ #
    # Public access
    # ------------------------------------------------------------------ #
    @classmethod
    def reload(cls) -> None:
        """Drop the cache so the next access reads disk again. For tests."""
        cls._cache.clear()

    @classmethod
    def category(cls, file_stem: str, category: str) -> Tuple[str, ...]:
        """Return synonyms for one ``(file_stem, category)`` pair."""
        return cls._load(file_stem).get(category, ())

    @classmethod
    def all_in_file(cls, file_stem: str) -> Tuple[str, ...]:
        """Flatten every synonym across every category of one file."""
        data = cls._load(file_stem)
        out: List[str] = []
        seen = set()
        for synonyms in data.values():
            for syn in synonyms:
                if syn in seen:
                    continue
                seen.add(syn)
                out.append(syn)
        return tuple(out)

    @classmethod
    def all_timestamp_fields(cls, priority: str = "real_first") -> Tuple[str, ...]:
        """All timestamp synonyms across every category in timestamps.json.

        ``priority='real_first'`` (default) puts real-activity timestamps
        (event_time, last_executed, creation_time, …) before parser
        bookkeeping (parsed_at, inserted_at, created_at). This matches
        the contract that ``_get_first_timestamp`` in the time-based
        engine wants: prefer the timestamp that describes when the
        artifact actually happened over the one describing when we
        ingested it.

        ``priority='flat'`` returns category order as-is.
        """
        data = cls._load("timestamps")
        if not data:
            return ()

        if priority == "flat":
            return cls.all_in_file("timestamps")

        # Real-activity categories first, in canonical order.
        real: List[str] = []
        seen = set()
        for cat in cls._REAL_TIMESTAMP_CATEGORIES:
            for syn in data.get(cat, ()):
                if syn in seen:
                    continue
                seen.add(syn)
                real.append(syn)

        # Any remaining non-bookkeeping categories.
        for cat, synonyms in data.items():
            if cat in cls._REAL_TIMESTAMP_CATEGORIES:
                continue
            if cat in cls._BOOKKEEPING_CATEGORIES:
                continue
            for syn in synonyms:
                if syn in seen:
                    continue
                seen.add(syn)
                real.append(syn)

        # Bookkeeping categories go straight to the back.
        bookkeeping: List[str] = []
        for cat in cls._BOOKKEEPING_CATEGORIES:
            for syn in data.get(cat, ()):
                if syn in seen:
                    continue
                seen.add(syn)
                bookkeeping.append(syn)

        # Re-sift in case a bookkeeping-suffix synonym (e.g. "*_at")
        # landed in a real-activity category by mistake.
        front: List[str] = []
        back: List[str] = bookkeeping[:]
        for syn in real:
            low = syn.lower()
            if any(low.endswith(suf) for suf in cls._BOOKKEEPING_SUFFIXES):
                back.append(syn)
            else:
                front.append(syn)

        return tuple(front + back)

    @classmethod
    def all_identity_fields(cls) -> Tuple[str, ...]:
        """All "what does this record describe?" synonyms, names first.

        Names (filename / app_name / process_name / display_name / …)
        precede paths (path / file_path / image_path / …). This
        ordering matches the contract that the engine's identity
        extractor wants: prefer a specific name field over a long path
        field when both are present.

        Sources: ``process_identifiers.json``, ``file_paths.json``,
        ``system_identifiers.json`` (device names), and the username
        category from ``user_identifiers.json``.
        """
        names: List[str] = []
        paths: List[str] = []
        seen = set()

        def _push(target: List[str], synonyms) -> None:
            for syn in synonyms:
                if syn in seen:
                    continue
                seen.add(syn)
                target.append(syn)

        # Process names (executablename, commandline, …)
        proc = cls._load("process_identifiers")
        _push(names, proc.get("executablename", ()))
        _push(names, proc.get("commandline", ()))

        # File-path names (filename, extension)
        fp = cls._load("file_paths")
        _push(names, fp.get("filename", ()))

        # Device / service / value names
        sys = cls._load("system_identifiers")
        _push(names, sys.get("devicename", ()))
        _push(names, sys.get("valuename", ()))
        _push(names, sys.get("description", ()))

        # Event channel / source
        ev = cls._load("event_identifiers")
        _push(names, ev.get("channel", ()))

        # User-side identity
        user = cls._load("user_identifiers")
        _push(names, user.get("username", ()))

        # Paths last
        _push(paths, fp.get("path", ()))
        _push(paths, fp.get("targetpath", ()))
        _push(paths, fp.get("sourcepath", ()))
        _push(paths, sys.get("keypath", ()))

        return tuple(names + paths)


__all__ = ["StandardFields"]
