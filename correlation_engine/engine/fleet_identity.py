"""Identity across machines (Sentinel 14.5), run by execute_wing_partitioned.

Every match of a partitioned run gets ``subject_keys``: the subjects its rows
are about, each a stable string built only from what the evidence records, so
the same account or the same executable gets the same key on every machine and
in every run. Where each key comes from:

**Users** (``user:...``), from the row's SID columns (StandardFields
``user_sid``), else its user-name columns:
- ``user:sid:<SID>`` for a domain or Azure AD SID (``S-1-5-21-`` with a domain
  part, ``S-1-12-1-``): one account wherever it signs in. A local account's SID
  already differs per machine (its machine part), so it never merges with
  another machine's account of the same name.
- ``user:sid:<SID>@<host>`` for a well-known SID (``S-1-5-18`` SYSTEM,
  ``S-1-5-19``/``-20``, ``S-1-5-32-...``): the same string names a different
  account on every machine.
- ``user:name:<domain>\\<name>`` for a name with a domain and no SID, and
  ``user:name:<name>@<host>`` for a bare name: never merged across machines on
  a name alone.

**Programs** (``file:...`` / ``program:...``):
- ``file:sha256:<hex>``, ``file:sha1:<hex>``, ``file:md5:<hex>`` when the row
  records the file's content hash (AmCache's ``0000``-prefixed SHA-1 is read
  as the 40-digit SHA-1). Prefetch's path hash is not a content hash and is
  not used.
- otherwise ``program:<name>``, the time-window engine's own identity
  (identity_grouping.identity_key over the declared program column), which is
  how the matches were grouped in the first place.

``partition_info['subjects']`` lists every key with its kind, source (sid /
name / sha256 / sha1 / md5 / program_name), hosts and match count.

**Propagation.** A conclusion about one record - a semantic rule result on a
match (``semantic_data``) or a fleet rule hit (engine/fleet_rules.py) - is
copied to every match sharing one of its subject keys, on any machine, under
``semantic_data['fleet_propagated']``: what was concluded, which rule, on which
host and match it was reached. The match it was reached on is not given a copy
of its own conclusion.
"""

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

# Well-known SIDs: the same string names a different account on every machine.
# Exact ones apart from prefixes: "S-1-5-2" (NETWORK) as a prefix would also
# match every "S-1-5-21-..." domain SID.
_WELL_KNOWN_EXACT = frozenset(("S-1-5-18", "S-1-5-19", "S-1-5-20", "S-1-1-0", "S-1-5-11",
                               "S-1-5-2", "S-1-5-4", "S-1-5-6", "S-1-5-7", "S-1-5-9"))
_WELL_KNOWN_PREFIXES = ("S-1-5-32-", "S-1-5-80-", "S-1-5-82-", "S-1-5-90-", "S-1-5-96-",
                        "S-1-15-")


def _fields(name):
    from utils.standard_fields import StandardFields
    try:
        return tuple(StandardFields.category("identities", name))
    except Exception:
        return ()


def _first(row, fields):
    for f in fields:
        v = row.get(f)
        if v is not None and str(v).strip() and str(v).strip() not in ("-", "N/A", "NULL"):
            return str(v).strip()
    return None


def user_key(row: Dict[str, Any], host: str) -> Optional[Tuple[str, str]]:
    """(key, source) for the account a row is about, or None."""
    sid = _first(row, _fields("user_sid"))
    if sid and sid.upper().startswith("S-1-"):
        sid = sid.upper()
        well_known = sid in _WELL_KNOWN_EXACT or sid.startswith(_WELL_KNOWN_PREFIXES)
        domain_wide = sid.startswith("S-1-5-21-") or sid.startswith("S-1-12-1-")
        if domain_wide and not well_known:
            return "user:sid:%s" % sid, "sid"
        return "user:sid:%s@%s" % (sid, host), "sid"
    name = _first(row, _fields("user_name"))
    if not name:
        return None
    name = name.lower()
    if "\\" in name:
        domain, _, account = name.partition("\\")
        if domain and account and domain not in ("nt authority", "builtin", "font driver host",
                                                 "window manager", "nt service"):
            return "user:name:%s\\%s" % (domain, account), "name"
        return "user:name:%s@%s" % (name, host), "name"
    return "user:name:%s@%s" % (name, host), "name"


def _hash(row) -> Optional[Tuple[str, str]]:
    for kind, n in (("sha256", 64), ("sha1", 40), ("md5", 32)):
        v = _first(row, _fields("hash_" + kind))
        if not v:
            continue
        v = v.lower()
        if kind == "sha1" and len(v) == 44 and v.startswith("0000"):
            v = v[4:]                                  # AmCache FileId
        if len(v) == n and all(c in "0123456789abcdef" for c in v):
            return "file:%s:%s" % (kind, v), kind
    return None


def program_key(row: Dict[str, Any], table: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """(key, source) for the program a row is about, or None."""
    hashed = _hash(row)
    if hashed:
        return hashed
    from .fleet_rules import _identity
    ident = _identity(table or "", row)
    return ("program:%s" % ident, "program_name") if ident else None


def _rows(match):
    from .partitioned import AGENT_COLUMN
    for fid, value in (match.feather_records or {}).items():
        for r in (value if isinstance(value, list) else [value]):
            if isinstance(r, dict):
                host = str(r.get(AGENT_COLUMN) or match.agent_id
                           or (match.hosts[0] if match.hosts else ""))
                yield fid, host, r


def _conclusions(match) -> List[Dict[str, Any]]:
    sd = match.semantic_data if isinstance(match.semantic_data, dict) else {}
    out = []
    for key in ("identity_semantic_results", "wing_rules", "semantic_mappings"):
        for entry in sd.get(key) or []:
            if isinstance(entry, dict) and (entry.get("rule_id") or entry.get("semantic_value")):
                out.append({"rule_id": entry.get("rule_id"),
                            "semantic_value": entry.get("semantic_value"),
                            "severity": entry.get("severity")})
    return out


def reconcile(result, tables: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Subject keys on every match, conclusions propagated (module docstring).
    ``tables``: feather_id -> data table, for the declared program column.
    Returns the subjects index."""
    tables = tables or {}
    subjects: Dict[str, Dict[str, Any]] = {}
    by_key: Dict[str, List[Any]] = defaultdict(list)
    for m in result.matches or []:
        keys = {"user": set(), "program": set()}
        for fid, host, row in _rows(m):
            for kind, got in (("user", user_key(row, host)),
                              ("program", program_key(row, tables.get(fid)))):
                if not got:
                    continue
                key, source = got
                keys[kind].add(key)
                s = subjects.setdefault(key, {"kind": kind, "source": source, "hosts": set(),
                                              "matches": set()})
                s["hosts"].add(host)
                s["matches"].add(m.match_id)
        m.subject_keys = {k: sorted(v) for k, v in keys.items() if v}
        for v in keys.values():
            for key in v:
                by_key[key].append(m)

    # What was concluded, by subject: each match's own semantic results, and
    # the fleet rule hits about a program identity.
    told: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for key, matches in by_key.items():
        for m in matches:
            for c in _conclusions(m):
                told[key].append(dict(c, subject=key, from_match=m.match_id,
                                      from_hosts=sorted(m.hosts or [])))
    for hit in getattr(result, "fleet_rule_hits", None) or []:
        if hit.get("identity") and hit.get("status") in ("fired", "absent"):
            key = "program:%s" % hit["identity"]
            if key in by_key:
                told[key].append({"rule_id": hit.get("rule_id"), "semantic_value": hit.get("status"),
                                  "rule_type": hit.get("rule_type"), "subject": key,
                                  "from_match": None, "from_hosts": list(hit.get("hosts") or [])})
    for key, conclusions in told.items():
        for m in by_key[key]:
            mine = [c for c in conclusions if c.get("from_match") != m.match_id]
            if not mine:
                continue
            if not isinstance(m.semantic_data, dict):
                m.semantic_data = {}
            have = m.semantic_data.setdefault("fleet_propagated", [])
            seen = {json.dumps(x, sort_keys=True, default=str) for x in have}
            for c in mine:
                text = json.dumps(c, sort_keys=True, default=str)
                if text not in seen:
                    seen.add(text)
                    have.append(c)
            have.sort(key=lambda c: json.dumps(c, sort_keys=True, default=str))
    return {k: {"kind": v["kind"], "source": v["source"], "hosts": sorted(v["hosts"]),
                "matches": len(v["matches"])} for k, v in sorted(subjects.items())}
