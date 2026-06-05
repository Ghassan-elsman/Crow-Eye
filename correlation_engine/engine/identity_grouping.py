"""
Identity Grouping — one normalization, one source of truth.

Crow-Eye historically had three separate identity-normalization
implementations: the engine's ``_normalize_identity`` (heavy), two GUI
``_sub_identity_key`` copies (mild), and the identity-semantic phase's
own ``_extract_identity_from_record``. They drifted out of sync,
producing different grouping behavior depending on which subsystem
processed the data.

This module is the canonical implementation. It exposes:

* :func:`identity_key` — heavy normalization for engine-level grouping.
                                Strips extension, version numbers, parens,
                                brackets, digits, noise words. Used for the
                                primary "what app is this?" bucket.

* :func:`sub_identity_key` — mild normalization for GUI display bucketing.
                                Case-folds and strips the executable
                                extension only. Preserves version numbers
                                and qualifiers so analysts can see
                                ``Chrome v1.0`` distinct from ``Chrome v2.0``.

* :func:`raw_identity` — pull the first non-empty identity field
                                from a record dict using the standard
                                fields registry's identity priority list.

Examples
--------
``identity_key('Chrome v1.0.exe')`` → ``"chrome"``
``identity_key('chrome.dll')`` → ``"chrome"``
``sub_identity_key('Chrome v1.0.exe')`` → ``"chrome v1.0"``
``sub_identity_key('chrome.dll')`` → ``"chrome"``
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Optional


# --------------------------------------------------------------------- #
# Extension sets
# --------------------------------------------------------------------- #

# Executable / shortcut / launcher extensions only.
# Stripping data extensions (.txt, .log, .ini, …) caused false dedup in
# the engine — distinct raw identities collapsed to the same normalized
# key. Keep this list narrow.
_EXTENSIONS: FrozenSet[str] = frozenset([
    '.exe', '.dll', '.sys', '.drv', '.ocx', '.cpl', '.scr',
    '.msi', '.msp', '.mst', '.bat', '.cmd', '.ps1', '.vbs',
    '.js', '.jse', '.wsf', '.wsh', '.lnk', '.pf',
    '.pif', '.com', '.jar',
])

# Words stripped when collapsing identity to a base form. Kept intentionally
# small — common English glue words that would otherwise survive the
# letter-only regex below.
_NOISE_WORDS: FrozenSet[str] = frozenset([
    'the', 'a', 'an', 'and', 'or', 'of', 'in', 'on', 'at', 'to', 'for',
])

# Precompiled regexes for heavy normalization.
_RE_VERSION_NUMBERS = re.compile(r'\s*v?\d+[\d.]*')
_RE_PARENTHESES = re.compile(r'\s*\(.*?\)')
_RE_BRACKETS = re.compile(r'\s*\[.*?\]')
_RE_NON_ALPHA = re.compile(r'[^a-z\s]')


# --------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------- #

def identity_key(raw_identity: str) -> str:
    """Engine-level **heavy** normalization. Aggressively collapses
    spelling variants into a single bucket so the time-window engine can
    group "chrome" evidence even when source artifacts spell it slightly
    differently across feathers.

    Transformations (in order): lowercase, strip executable extension,
    strip version numbers (``\\s*v?\\d+[\\d.]*``), strip parenthetical
    content, strip bracket content, drop everything that isn't a letter,
    drop noise words. Lowercased throughout.

    **Collapse side effects — be aware of these false positives.** This
    function intentionally over-collapses to maximize recall; callers
    who care about distinguishing versions or architectures must use
    :func:`sub_identity_key` instead:

    - ``"chrome.exe"`` and ``"chrome2.exe"`` → both ``"chrome"``
      (digits stripped — distinct major versions look identical).
    - ``"c++.exe"`` and ``"c#.exe"`` → both ``"c"`` (non-letter symbols
      dropped — distinct languages look identical).
    - ``"firefox (32-bit)"`` and ``"firefox (64-bit)"`` → both
      ``"firefox"`` (parens stripped — distinct architectures collapse).
    - ``"Chrome.exe"``, ``"chrome.exe"``, ``"Chrome.EXE"``,
      ``"chrome.dll"`` → all ``"chrome"`` (the intended trivial-variant
      collapse — this is the *desired* behavior).

    Returns an empty string if the input normalizes away entirely
    (e.g. ``"1.2.3"`` → ``""``); callers should treat empty as "no
    extractable identity".

    See also: :func:`sub_identity_key` — preserves version + architecture
    distinctions for analyses where chrome v1 vs v2 matters.
    """
    if not raw_identity:
        return ""

    s = str(raw_identity).lower()

    # Strip a single matching extension
    for ext in _EXTENSIONS:
        if s.endswith(ext):
            s = s[:-len(ext)]
            break

    # Remove version / parens / brackets / non-letters
    s = _RE_VERSION_NUMBERS.sub('', s)
    s = _RE_PARENTHESES.sub('', s)
    s = _RE_BRACKETS.sub('', s)
    s = _RE_NON_ALPHA.sub('', s)

    # Collapse whitespace; drop noise words
    words = [w for w in s.split() if w and w not in _NOISE_WORDS]
    return ' '.join(words).strip()


def sub_identity_key(raw_identity: str) -> str:
    """GUI-level mild normalization for sub-identity bucketing.

    Less aggressive than :func:`identity_key`: only case-folds and strips
    the executable extension. Preserves version numbers and qualifiers
    so analysts can distinguish ``"chrome v1.0"`` from ``"chrome v2.0"``.

    Trivial spelling variants of the same artifact ("Chrome.exe",
    "chrome.exe", "Chrome.EXE", "chrome.dll") collapse to ``"chrome"``.
    """
    if not raw_identity:
        return ""
    s = str(raw_identity).strip().lower()
    for ext in _EXTENSIONS:
        if s.endswith(ext):
            s = s[:-len(ext)]
            break
    return s.strip()


def raw_identity(record: Dict[str, Any], field_priority=None) -> Optional[str]:
    """Extract the first non-empty identity field from ``record``.

    By default uses ``StandardFields.all_identity_fields()`` (names before
    paths). Callers can pass a custom priority list — e.g. a per-table
    list from ``feather_schemas.json`` — to narrow the search.

    Returns ``None`` when no field carries usable content.
    """
    if not isinstance(record, dict):
        return None

    if field_priority is None:
        try:
            from utils.standard_fields import StandardFields
            field_priority = StandardFields.all_identity_fields()
        except Exception:
            field_priority = ()

    for field in field_priority:
        value = record.get(field)
        if not value:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


__all__ = ["identity_key", "sub_identity_key", "raw_identity"]
