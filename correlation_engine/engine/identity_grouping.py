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
# Display grouping (shared by GUI unified view and the run-level
# identity reconciler). Deliberately SEPARATE from _EXTENSIONS /
# identity_key: this is the richer normalization the results view has
# always used (Prefetch hashes, ~-truncation, copy markers, digit
# stripping). Keep engine correlation grouping (identity_key) untouched.
# --------------------------------------------------------------------- #

_DISPLAY_GROUP_EXTENSIONS = [
    '.exe', '.lnk', '.dll', '.msi', '.bat', '.cmd', '.ps1', '.vbs', '.js',
    '.com', '.scr', '.pif', '.application', '.gadget', '.msp', '.hta',
    '.cpl', '.msc', '.jar', '.py', '.pyc', '.pyw'
]

_RE_PREFETCH_NAME = re.compile(r'^(.+?)\s+[0-9A-Fa-f]{8}\.pf$', re.IGNORECASE)
_RE_COPY_NUMBER = re.compile(r'[\s_]*\(\d+\)\s*$')
_RE_COPY_WORD = re.compile(r'[\s_]*[-_]?\s*[Cc]opy\s*\d*\s*$')
_RE_COPY_PAREN = re.compile(r'[\s_]*\([Cc]opy\s*\d*\)\s*$')
_RE_TRAILING_VERSION_SEP = re.compile(r'[\s_]+[vV]?\d+(\.\d+)*\s*$')
_RE_TRAILING_VERSION_V = re.compile(r'[vV]\d+(\.\d+)*\s*$')
_RE_SEPARATORS = re.compile(r'[\s\-_\.\(\)\[\]]+')
_RE_NON_ALNUM = re.compile(r'[^a-z0-9]')
_RE_DIGITS = re.compile(r'\d+')

# Field priority lists for extract_original_name (mirrors the GUI's
# historical evidence-name extraction).
_ORIGINAL_NAME_FIELDS = [
    'name', 'filename', 'file_name', 'fn_filename', 'executable_name',
    'Source_Name', 'original_filename', 'app_name', 'value', 'Value',
    'FileName', 'Name'
]
_ORIGINAL_PATH_FIELDS = ['path', 'file_path', 'Local_Path', 'app_path', 'full_path']


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


def display_grouping_key(name: Optional[str]) -> str:
    """Aggressive display-level grouping key for MAIN identities.

    Canonical implementation of the normalization the results GUI has
    always used to fold matches into one main identity
    ("chrome.exe", "CHROME~1.EXE", "chrome123.exe" → "chrome").
    Shared by ``IdentityResultsView._normalize_for_grouping`` and the
    cross-wing run reconciler so the persisted registry and the rendered
    tree group identically.

    LIMITATION: only ASCII alphanumerics survive; Unicode letters are
    removed (acceptable for Windows forensics artifact names).
    """
    if not name:
        return "Unknown"

    result = str(name).strip()

    # Step -1: Prefetch filenames "APPNAME.EXE HASH.pf" → "APPNAME.EXE"
    if result.lower().endswith('.pf'):
        match = _RE_PREFETCH_NAME.match(result)
        if match:
            result = match.group(1)

    # Step 0: remove ~ and everything after (8.3 short names: CHROME~1.EXE)
    if '~' in result:
        result = result.split('~')[0]

    # Step 1: strip one known extension (case-insensitive)
    lower_result = result.lower()
    for ext in _DISPLAY_GROUP_EXTENSIONS:
        if lower_result.endswith(ext):
            result = result[:-len(ext)]
            break

    # Steps 2-3: copy indicators — "(1)", " - Copy", "(copy 2)"
    result = _RE_COPY_NUMBER.sub('', result)
    result = _RE_COPY_WORD.sub('', result)
    result = _RE_COPY_PAREN.sub('', result)

    # Step 4: trailing versions — requires separator or explicit v prefix
    # so digits that are part of the name survive ("chrome1")
    result = _RE_TRAILING_VERSION_SEP.sub('', result)
    result = _RE_TRAILING_VERSION_V.sub('', result)

    # Step 5: aggressive collapse — lowercase, drop separators/specials
    result = result.lower()
    result = _RE_SEPARATORS.sub('', result)
    result = _RE_NON_ALNUM.sub('', result)

    # Step 6: drop ALL digits ("chrome1"/"chrome2" → "chrome")
    result = _RE_DIGITS.sub('', result)

    # Fallback: milder pass keeping digits, so pure-numeric names survive
    if not result:
        result = str(name).strip().lower()
        if '~' in result:
            result = result.split('~')[0]
        result = _RE_SEPARATORS.sub('', result)
        result = _RE_NON_ALNUM.sub('', result)

    return result.strip() if result else "Unknown"


def extract_original_name(raw_app: str, feather_records: Dict[str, Any]) -> str:
    """Pick the most representative original name for a match's evidence.

    Mirrors the results GUI's historical extraction: prefer an explicit
    name field from any evidence record, then a filename pulled from a
    path field, falling back to ``raw_app``. Shared by the GUI sub-identity
    bucketing and the cross-wing run reconciler.
    """
    original_name = raw_app
    if not isinstance(feather_records, dict):
        return original_name

    from pathlib import Path

    for _fid, data in feather_records.items():
        if not isinstance(data, dict):
            continue
        for field in _ORIGINAL_NAME_FIELDS:
            if field in data and data[field]:
                original_name = str(data[field])
                break
        if original_name != raw_app:
            break
        for field in _ORIGINAL_PATH_FIELDS:
            if field in data and data[field]:
                path_val = str(data[field])
                if '\\' in path_val or '/' in path_val:
                    extracted_name = Path(path_val.replace('\\', '/')).name
                    if extracted_name:
                        original_name = extracted_name
                        break
        if original_name != raw_app:
            break
    return original_name


__all__ = [
    "identity_key", "sub_identity_key", "raw_identity",
    "display_grouping_key", "extract_original_name",
]
