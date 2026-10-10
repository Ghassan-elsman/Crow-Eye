"""What a Windows event means, keyed by (provider, EventID).

The live parser used to carry a 95-entry dictionary keyed by the event ID
ALONE, and the offline parser had no text at all. An ID only means something
together with the provider that wrote it, so the ID-only lookup put wrong
words on real rows - EventSystem 4625 read "An account failed to log on",
Winlogon 7001 read "The service started successfully", MsiInstaller 1033
(a product was installed) read "Application performance monitoring started" -
and on a real case 89% of System rows, 67% of Security and 26% of Application
had no description at all.

The table is data: ``configs/event_descriptions.json``. ``describe()`` gives

* the exact text for (provider, ID), with ``%1..%n`` filled from the event's
  inserts (live) or EventData values (offline) when they are given;
* otherwise what the provider is ("Bluetooth USB radio driver, event 3"), so
  a row always says where it came from;
* otherwise a sentence saying Crow-Eye has no description for it - never a
  description that belongs to a different provider.

Provider names match case-insensitively, with or without the
``Microsoft-Windows-`` prefix; legacy event-source names (what the live API
reports, e.g. "Software Protection Platform Service") are mapped by
``aliases``.
"""

import json
import logging
import os
import re
import sys
from typing import Dict, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

NO_DESCRIPTION = "No description in Crow-Eye's event catalogue"
_PLACEHOLDER = re.compile(r"%(\d{1,2})")
_CACHE: Optional[Tuple[Dict[str, Dict[str, str]], Dict[str, str], Dict[str, str]]] = None


def _catalogue_path() -> Optional[str]:
    roots = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        roots.append(base)
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for root in roots:
        p = os.path.join(root, "configs", "event_descriptions.json")
        if os.path.isfile(p):
            return p
    return None


def normalise_provider(name: Optional[str]) -> str:
    """'Microsoft-Windows-Kernel-Power' and 'Kernel-Power' -> 'kernel-power'."""
    n = (name or "").strip().lower()
    if n.startswith("microsoft-windows-"):
        n = n[len("microsoft-windows-"):]
    return n


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    events, about, aliases = {}, {}, {}
    path = _catalogue_path()
    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for alias, target in (data.get("aliases") or {}).items():
                aliases[normalise_provider(alias)] = normalise_provider(target)
            for provider, entry in (data.get("providers") or {}).items():
                key = normalise_provider(provider)
                if entry.get("about"):
                    about[key] = entry["about"]
                for eid, text in (entry.get("events") or {}).items():
                    events.setdefault(key, {})[str(int(eid))] = text
        except Exception as exc:
            logger.warning("Event description catalogue not loaded (%s): %s", path, exc)
    else:
        logger.warning("Event description catalogue configs/event_descriptions.json not found")
    _CACHE = (events, about, aliases)
    return _CACHE


def reload_catalogue():
    """Forget the cached table (tests, or after editing the JSON)."""
    global _CACHE
    _CACHE = None


def _fill(text: str, inserts: Optional[Sequence]) -> str:
    """Put inserts into %1..%n; a placeholder with no insert becomes '?'."""
    values = [("" if v is None else str(v)).strip() for v in (inserts or [])]

    def sub(m):
        i = int(m.group(1)) - 1
        if 0 <= i < len(values) and values[i]:
            return values[i]
        return "?"

    return _PLACEHOLDER.sub(sub, text)


def lookup(provider: Optional[str], event_id) -> Tuple[Optional[str], str]:
    """(template or None, provider about-text or '') - no inserts filled."""
    events, about, aliases = _load()
    key = normalise_provider(provider)
    key = aliases.get(key, key)
    try:
        eid = str(int(str(event_id).strip()) & 0xFFFF)
    except (TypeError, ValueError):
        eid = str(event_id).strip()
    return (events.get(key) or {}).get(eid), about.get(key, "")


def describe(provider: Optional[str], event_id, inserts: Optional[Sequence] = None) -> str:
    """The sentence for this event. Never empty, never another provider's text."""
    template, about = lookup(provider, event_id)
    if template:
        return _fill(template, inserts) if inserts is not None else _PLACEHOLDER.sub("?", template)
    if about:
        return "%s, event %s (no text for this ID in Crow-Eye's catalogue)" % (about, event_id)
    return "%s (%s, event %s)" % (NO_DESCRIPTION, provider or "unknown source", event_id)


def has_text(provider: Optional[str], event_id) -> bool:
    """True when the catalogue has an exact sentence for this event."""
    return lookup(provider, event_id)[0] is not None
