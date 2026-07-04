#!/usr/bin/env python3
"""
build_evidence_map.py — auto-generate the Narrative Map graph from a case's
EYE report workspace.

Reads <case>/EYE_Logs/eye_report_workspace.json and emits the {narratives,
evidence, conclusions, links} JSON used to seed the Narrative Map. Loaded by
`narrative_map_service._seed_graph()` and normalized into the MapGraph that
`NarrativeMap.tsx` renders.

Rules (all automatic, no hand-curation):
  - Each markdown narrative block  -> a Narrative/Finding container.
    A block whose title/heading mentions "conclusion" or "verdict" becomes the
    Conclusion (verdict) node instead.
  - Each SQL-backed data block / timeline -> an Evidence card. The source table
    is parsed from the SQL `FROM` clause (falls back to the caption).
  - Evidence is assigned to the narrative with the highest keyword overlap
    (caption + table vs. narrative title + body). Unmatched evidence goes to an
    "Unassigned evidence" container so nothing is hidden.
  - Every narrative links to the verdict.

Usage:  python build_evidence_map.py "<case folder>"  > evidence_map.json
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

STOP = set("the a an and or of to in on for with without is are was were be been being this that these those it its by as at from into via not no yes does do did using used use during over under across each any all their his her them they we i you your our".split())

def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", (s or "").lower()) if w not in STOP}

def table_from_sql(sql: str, caption: str) -> str:
    m = re.search(r"\bFROM\s+([A-Za-z_][\w]*)", sql or "", re.I)
    if m:
        return m.group(1)
    # captions like "Recent Prefetch Executions" -> first capitalized keyword
    for kw in ("Prefetch", "Amcache", "SRUM", "USN", "MFT", "Registry", "Service",
               "Security", "LNK", "JumpList", "Browser", "USB", "Network", "Run"):
        if kw.lower() in (caption or "").lower():
            return kw
    return (caption or "Evidence").split(" ")[0]

def first_value(rows):
    if rows and isinstance(rows[0], dict):
        for v in rows[0].values():
            if v not in (None, "", "N/A"):
                return str(v)[:48]
    return ""

def load_blocks(case: Path):
    rw = case / "EYE_Logs" / "eye_report_workspace.json"
    data = json.loads(rw.read_text(encoding="utf-8"))
    return data.get("blocks", [])

# Triage observation blocks that are surfaced as FLOATING GLOBAL cards (by the
# triage's upsert_global), not verdict-linked narratives — skip them in the seed so
# they don't appear twice on the Narrative Map.
GLOBAL_BLOCK_TITLES = {"system identity", "immediate technical observations", "technical observations"}


def build(case: Path) -> dict:
    blocks = load_blocks(case)
    narratives, evidence, conclusion = [], {}, None

    # 1) narratives + conclusion
    for b in blocks:
        md = b.get("markdown_content")
        if not md:
            continue
        title = (b.get("title") or "Finding").strip()
        if title.lower() in GLOBAL_BLOCK_TITLES:
            continue  # floating global card, not a verdict narrative
        nid = b.get("block_id") or f"n{len(narratives)}"
        body = title + " " + md
        node = {"id": nid, "title": title, "summary": md.strip()[:600],
                "keywords": list(words(body)), "evs": []}
        if re.search(r"conclusion|verdict|final audit", title, re.I) and conclusion is None:
            conclusion = {"id": nid, "data": title, "reason": md.strip()[:160]}
        else:
            narratives.append(node)

    # 2) evidence cards
    cards = []
    for b in blocks:
        if "sql_query" not in b and b.get("block_type") not in ("timeline",):
            continue
        cap = b.get("caption") or b.get("title") or ""
        if not cap and "events" in b:  # timeline
            cap = b.get("title") or "Timeline"
        table = table_from_sql(b.get("sql_query", ""), cap)
        rows = b.get("rows") or b.get("events") or []
        eid = b.get("block_id") or f"e{len(cards)}"
        cards.append({
            "id": eid, "kicker": table, "data": cap or table,
            "reason": f"{len(rows)} rows" + (f" · {first_value(rows)}" if first_value(rows) else ""),
            "ref": table, "authoredBy": "system", "evidence": [f"{table}:rows"],
            "keywords": list(words(cap + " " + table)), "notes": [],
        })

    # 3) assign evidence -> best narrative by keyword overlap
    unassigned = {"id": "n_unassigned", "title": "Unassigned evidence",
                  "summary": "Auto-parser could not confidently attach these to a finding.",
                  "keywords": [], "evs": []}
    for c in cards:
        ckw = set(c["keywords"])
        best, score = None, 0
        for n in narratives:
            ov = len(ckw & set(n["keywords"]))
            if ov > score:
                best, score = n, ov
        (best or unassigned)["evs"].append(c["id"])
        evidence[c["id"]] = {k: c[k] for k in ("id", "kicker", "data", "reason", "ref", "authoredBy", "evidence", "notes")}
    if unassigned["evs"]:
        narratives.append(unassigned)

    if conclusion is None:
        conclusion = {"id": "verdict", "data": "Overall verdict", "reason": "Synthesis of findings"}

    # 4) layout + links
    for i, n in enumerate(narratives):
        n["x"], n["y"] = 250, 18 + i * 150
        n.pop("keywords", None)
        n["data"] = n.pop("title")
        n["reason"] = n.pop("summary")
        n["authoredBy"] = "eye:gemma-4-31b-it"
    conclusion.update({"x": 600, "y": 200, "authoredBy": "eye:gemma-4-31b-it", "notes": []})
    links = [{"id": f"l{i}", "from": n["id"], "to": conclusion["id"]} for i, n in enumerate(narratives)]

    return {"narratives": narratives, "evidence": evidence,
            "conclusions": [conclusion], "links": links}

if __name__ == "__main__":
    case = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    print(json.dumps(build(case), indent=2, ensure_ascii=False))
