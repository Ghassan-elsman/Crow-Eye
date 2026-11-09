"""AI agent session records from collected evidence (an offline folder or an image).

The live parser (AI_Agent_Claw.py) reads <partition>\\Users. Offline, the
collectors keep each profile's agent folders at
    <case>\\live_acquisition\\AIAgents\\<source>\\Users\\<name>\\.claude\\projects\\...
                                                         \\.gemini\\tmp\\...
                                                         \\.codex\\sessions\\...
one <source> per image partition or imported folder (the Browser tree's
layout), so two machines' profiles never merge. A mounted image or a folder
that already holds a Users tree can be passed directly.

The rows are the same as live: one parser, AI_Agent_Claw.parse_users_root.
user_name is the evidence's own profile folder name, never this machine's.
"""

import glob
import logging
import os
from typing import Iterable, List, Optional

from Artifacts_Collectors.AI_Agent_Claw import DB_NAME, parse_users_root

logger = logging.getLogger(__name__)

CASE_DIR = "AIAgents"          # live_acquisition\AIAgents\<source>\Users\<name>\...


def users_roots_in_case(case_root: str) -> List[str]:
    """Every collected Users folder under live_acquisition\\AIAgents."""
    base = os.path.join(case_root or "", "live_acquisition", CASE_DIR)
    return sorted(p for p in glob.glob(os.path.join(base, "*", "Users")) if os.path.isdir(p))


def _as_users_root(path: str) -> Optional[str]:
    """A Users folder from a path the caller found: the folder itself, a
    volume root holding Users, or a path inside a profile."""
    p = os.path.abspath(path)
    if os.path.basename(p).lower() == "users" and os.path.isdir(p):
        return p
    if os.path.isdir(os.path.join(p, "Users")):
        return os.path.join(p, "Users")
    parts = p.split(os.sep)
    low = [x.lower() for x in parts]
    if "users" in low:
        i = len(low) - 1 - low[::-1].index("users")
        return os.sep.join(parts[:i + 1])
    return None


def run_offline_ai_agents(case_root: str, target_artifacts_dir: Optional[str] = None,
                          users_roots: Optional[Iterable[str]] = None) -> dict:
    """Parse every collected (or given) Users tree into Target_Artifacts\\ai_agents.db."""
    target = target_artifacts_dir or os.path.join(case_root, "Target_Artifacts")
    db_path = os.path.join(target, DB_NAME)
    roots, seen = [], set()
    for r in list(users_roots or []) + users_roots_in_case(case_root):
        u = _as_users_root(r)
        key = os.path.normcase(u) if u else None
        if u and key not in seen:
            seen.add(key)
            roots.append(u)
    if not roots:
        return {"success": True, "status": "source_not_found", "records": 0, "output_path": db_path,
                "message": "No AI agent session folders were found in the collected evidence."}
    total = {"records": 0, "inserted": 0, "duplicates": 0, "files": 0, "unchanged_files": 0,
             "errors": 0, "tables": {}, "warnings": []}
    # The profiles' owners from the case's own SOFTWARE hive - never this
    # machine's. A collected hive cannot be tied to one of several sources,
    # so with more than one Users tree no SID is given (the Browser rule).
    sid_map = {}
    try:
        from Artifacts_Collectors.offline_parsers.offline_BrowserClaw import evidence_sid_map
        sid_map = evidence_sid_map(case_root)
    except Exception as exc:
        print("[AI agents] No SIDs from the case's hives (%s)" % exc)
    if len(roots) > 1 and sid_map:
        total["warnings"].append("This case holds %d Users trees; SIDs were not assigned, because a "
                                 "collected SOFTWARE hive cannot be tied to one source." % len(roots))
        sid_map = {}
    for root in roots:
        print("[AI agents] Reading %s" % root)
        r = parse_users_root(root, db_path, sid_map=sid_map)
        for k in ("records", "inserted", "duplicates", "files", "unchanged_files", "errors"):
            total[k] += int(r.get(k) or 0)
        for t, v in (r.get("tables") or {}).items():
            agg = total["tables"].setdefault(t, {"parsed": 0, "inserted": 0, "duplicates": 0})
            for k in agg:
                agg[k] += v.get(k, 0)
    total.update(success=True, output_path=db_path, users_roots=roots)
    return total


__all__ = ["run_offline_ai_agents", "users_roots_in_case", "CASE_DIR"]
