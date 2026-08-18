"""
NarrativeMapService — the Eye's persistent, auditable, tamper-evident working memory.

The Eye (a gemma-class LLM) is stateless between turns. The Narrative Map is the
single place where "what we know and what we have concluded" lives for a case, as a
strict hierarchy:

    Verdict   — the top-level conclusion the investigation drives toward (1 per case)
      ^
    Narrative — a theme / claim being established; has a State (see ``STATES``)
      ^
    Evidence  — an artifact-backed fact; lives inside a narrative, or free (floating)

This service owns the on-disk truth and is the single mutation choke point:

  * ``<case>/EYE_Logs/narrative_map.json``         — the MapGraph (UI + prompt read it)
  * ``<case>/EYE_Logs/narrative_map_audit.jsonl``  — hash-chained audit (chain of custody)

Every change — by the Eye OR the investigator — flows through :meth:`commit`, which
validates the Ghassan Elsman Protocol (GEP) rules, stamps authorship, applies the
mutation, persists the graph, and seals a hash-chained audit record (same
non-repudiation property as :class:`~eye.services.evidence_seal.EvidenceSeal`).

Because both prompt tiers read ``narrative_map.json`` fresh each turn, ANY edit or
note an investigator makes in the map UI is automatically in the Eye's next prompt:

  * Tier A — :meth:`overview_block`  → compact ``## Case Memory`` (one line/narrative)
  * Tier B — :meth:`relevant_slice` → per sub-question expansion incl. investigator
    notes verbatim, so human guidance actually steers the model.

GEP rules enforced here (mirroring ``correlation_engine/config/eye_authorship.py``):
  * R9  Reason-Required (hard)  — ``reason`` must be non-empty.
  * R10 Evidence-Link  (soft)   — a narrative needs >=1 evidence ref; the ONLY
        sanctioned exemption is an investigator-authored ``absolute`` (or ``needs``)
        narrative. Otherwise it is logged ``partially_satisfied``.
  * R11 Eye-Stamped             — every Eye write carries an eye authorship stamp.

An Eye-authored narrative must never assert the unsupported: it may not drop to zero
evidence. A checked-and-empty Eye theme is auto-converted to ``negative`` (absence is
the finding); creating an Eye narrative with no evidence is rejected.
"""

from __future__ import annotations

import json
import hashlib
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# State vocabulary (kept in sync with the React STATE_META map).
STATES = ("proven", "open", "negative", "needs", "absolute")

# Verdict lifecycle (Phase 1): the existing color = "open" (still under
# investigation), plus the two conclusions the investigator/Eye can set.
VERDICT_STATES = ("open", "proven", "unproven")

# States a narrative may legitimately hold with zero evidence — and only when
# investigator-authored (a human hypothesis or a stipulated absolute fact).
ZERO_EVIDENCE_STATES = ("needs", "absolute")

# Audited event types (must match the React union).
ACTIONS = (
    "CREATE", "EDIT", "STATE_CHANGE", "ATTACH", "DETACH", "MAKE_ABSOLUTE",
    "MAKE_BASE", "MARK_NEGATIVE", "NOTE", "LINK", "UNLINK", "DELETE", "MOVE",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


_STOP = set(
    "the a an and or of to in on for with without is are was were be been being this "
    "that these those it its by as at from into via not no yes does do did using used "
    "use during over under across each any all their them they we you your our".split()
)


def _tokenize(text: str) -> set:
    import re
    return {
        w for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", (text or "").lower())
        if w not in _STOP
    }


class NarrativeMapService:
    """Loads/saves the Narrative Map, validates GEP, seals a hash-chained audit,
    and emits the Eye's two-tier context blocks. Best-effort throughout: a map
    failure must never break the investigation pipeline."""

    def __init__(
        self,
        case_directory: Optional[Union[str, Path]],
        eye_version: str = "",
        model_name: str = "eye",
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.case_directory = Path(case_directory) if case_directory else None
        self.eye_version = eye_version
        self.model_name = model_name or "eye"
        self._lock = threading.RLock()

        self._map_path: Optional[Path] = None
        self._audit_path: Optional[Path] = None
        self._seq = 0
        self._prev_hash = ""
        self._graph: Optional[Dict[str, Any]] = None
        self._uid = 0  # monotonic counter so rapid id generation never collides

        if self.case_directory:
            logs = self.case_directory / "EYE_Logs"
            self._map_path = logs / "narrative_map.json"
            self._audit_path = logs / "narrative_map_audit.jsonl"
            self._recover_chain()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _recover_chain(self) -> None:
        """Resume seq + prev_hash from an existing audit log so the chain stays
        continuous across sessions (tamper-evident)."""
        try:
            if self._audit_path and self._audit_path.exists():
                last = None
                with open(self._audit_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            last = line
                if last:
                    rec = json.loads(last)
                    self._seq = int(rec.get("seq", 0))
                    self._prev_hash = rec.get("hash", "") or ""
        except Exception as e:
            self.logger.warning(f"Could not recover narrative-map audit chain: {e}")

    def _default_graph(self) -> Dict[str, Any]:
        return {
            "verdict": {
                "id": "verdict",
                "title": "Overall verdict",
                "reason": "Synthesis of the narratives below.",
                "state": "open",
                "authoredBy": f"eye:{self.model_name}",
            },
            "narratives": [],
            "evidence": {},
            # Global cards (System Identity, Technical Observations, free notes) —
            # unconnected by default; float in the left zone, linkable later.
            "globals": [],
            "links": [],
        }

    @staticmethod
    def _normalize_graph(d: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce any accepted shape (backend MapGraph, or the build_evidence_map.py
        seed shape ``{narratives, evidence, conclusions|verdict, links}``) into the
        canonical MapGraph the UI + prompt expect."""
        d = d or {}
        # Verdict: explicit, or first of conclusions, or default.
        verdict = d.get("verdict")
        if not verdict:
            concls = d.get("conclusions") or []
            if concls:
                c = concls[0]
                verdict = {
                    "id": c.get("id", "verdict"),
                    "title": c.get("data") or c.get("title") or "Overall verdict",
                    "reason": c.get("reason", ""),
                    "authoredBy": c.get("authoredBy", "eye"),
                }
        if not verdict:
            verdict = {"id": "verdict", "title": "Overall verdict", "reason": "", "authoredBy": "eye"}
        # Carry the verdict's free-form board position through (None until dragged).
        v_state = verdict.get("state")
        if v_state not in VERDICT_STATES:
            v_state = "open"
        verdict = {
            "id": verdict.get("id", "verdict"),
            "title": verdict.get("title") or verdict.get("data") or "Overall verdict",
            "reason": verdict.get("reason", ""),
            "state": v_state,
            "authoredBy": verdict.get("authoredBy", "eye"),
            "x": verdict.get("x"),
            "y": verdict.get("y"),
        }

        narratives = []
        for n in (d.get("narratives") or d.get("reasonings") or []):
            state = n.get("state")
            if state not in STATES:
                state = "open"
            narratives.append({
                "id": n.get("id"),
                "state": state,
                "title": n.get("title") or n.get("data") or "Narrative",
                "reason": n.get("reason") or n.get("summary") or "",
                "authoredBy": n.get("authoredBy", "eye"),
                "evs": list(n.get("evs") or []),
                "notes": list(n.get("notes") or []),
                "collapsed": bool(n.get("collapsed", False)),
                # Provenance: how this narrative was created (e.g. the sub-question
                # that raised it). Kept as metadata — NOT shown as the card title.
                "meta": dict(n.get("meta") or {}),
                # Free-form board position (None until the investigator drags it).
                "x": n.get("x"),
                "y": n.get("y"),
            })

        evidence = {}
        for eid, e in (d.get("evidence") or {}).items():
            evidence[eid] = {
                "id": e.get("id", eid),
                "kicker": e.get("kicker", "artifact"),
                "data": e.get("data", ""),
                # Full captured text (non-DB / text-mode evidence stays viewable even
                # without a reloadable source). Empty for older cards.
                "content": e.get("content", ""),
                "reason": e.get("reason", ""),
                "ref": e.get("ref") or (e.get("evidence") or [""])[0] if e.get("evidence") else e.get("ref", ""),
                # Source query + database so the detail window can reload real rows.
                "query": e.get("query", ""),
                "database": e.get("database", ""),
                "authoredBy": e.get("authoredBy", "system"),
                "sealed": e.get("sealed"),
                "notes": list(e.get("notes") or []),
                "free": bool(e.get("free", False)),
                "x": e.get("x"),
                "y": e.get("y"),
            }

        # Global cards: free-floating observations / notes (System Identity,
        # Technical Observations, investigator notes). No links by default.
        globals_ = []
        for gC in (d.get("globals") or []):
            globals_.append({
                "id": gC.get("id"),
                "kicker": gC.get("kicker", "note"),
                "title": gC.get("title") or gC.get("data") or "Note",
                "body": gC.get("body") or gC.get("reason") or "",
                "authoredBy": gC.get("authoredBy", "eye"),
                "notes": list(gC.get("notes") or []),
                "x": gC.get("x"),
                "y": gC.get("y"),
            })

        links = []
        for l in (d.get("links") or []):
            links.append({
                "id": l.get("id"),
                "from": l.get("from") or l.get("source"),
                "to": l.get("to") or l.get("target") or verdict["id"],
            })

        return {"verdict": verdict, "narratives": narratives, "evidence": evidence,
                "globals": globals_, "links": links}

    def load_graph(self) -> Dict[str, Any]:
        """Return the case MapGraph, loading from disk (or seeding) once and caching."""
        with self._lock:
            if self._graph is not None:
                return self._graph
            graph = None
            try:
                if self._map_path and self._map_path.exists():
                    graph = self._normalize_graph(json.loads(self._map_path.read_text(encoding="utf-8")))
            except Exception as e:
                self.logger.warning(f"Could not read narrative_map.json: {e}")
            if graph is None:
                graph = self._seed_graph()
            self._graph = graph
            return self._graph

    def _seed_graph(self) -> Dict[str, Any]:
        """Seed from the case report workspace via build_evidence_map.py if possible,
        else an empty graph."""
        if self.case_directory:
            try:
                import importlib.util
                # build_evidence_map.py lives under eye/ui/react/src/ (not a Python
                # package), so load it directly by file path.
                bem_path = (Path(__file__).resolve().parent.parent
                            / "ui" / "react" / "src" / "build_evidence_map.py")
                if bem_path.exists():
                    spec = importlib.util.spec_from_file_location("build_evidence_map", bem_path)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)  # type: ignore[union-attr]
                    seed = mod.build(self.case_directory)
                    return self._normalize_graph(seed)
            except Exception as e:
                self.logger.debug(f"Narrative-map seed parser unavailable: {e}")
        return self._default_graph()

    def load_graph_json(self) -> str:
        """MapGraph as a JSON string (for the bridge), with recent audit attached
        so the map's Audit tab can render history on open."""
        try:
            graph = dict(self.load_graph())
            graph["audit"] = self.recent_audit(limit=200)
            graph["chain_intact"] = self.verify_chain()
            return json.dumps(graph, ensure_ascii=False, default=str)
        except Exception as e:
            self.logger.error(f"load_graph_json failed: {e}")
            return json.dumps(self._default_graph())

    def _save(self) -> None:
        if not self._map_path or self._graph is None:
            return
        try:
            self._map_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._map_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._graph, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            tmp.replace(self._map_path)
        except Exception as e:
            self.logger.error(f"Could not persist narrative_map.json: {e}")

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #
    def _narrative(self, nid: str) -> Optional[Dict[str, Any]]:
        for n in self.load_graph()["narratives"]:
            if n["id"] == nid:
                return n
        return None

    def _narrative_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        t = (title or "").strip().lower()
        if not t:
            return None
        for n in self.load_graph()["narratives"]:
            if (n.get("title") or "").strip().lower() == t:
                return n
        return None

    def _narrative_by_created_from(self, question: str) -> Optional[Dict[str, Any]]:
        """Find a narrative by the originating question stored in its metadata
        (so a finding-narrative is updated, not duplicated, across turns)."""
        q = (question or "").strip().lower()
        if not q:
            return None
        for n in self.load_graph()["narratives"]:
            if ((n.get("meta") or {}).get("created_from") or "").strip().lower() == q:
                return n
        return None

    def _owner_of(self, eid: str) -> Optional[Dict[str, Any]]:
        for n in self.load_graph()["narratives"]:
            if eid in n.get("evs", []):
                return n
        return None

    def _new_id(self, prefix: str) -> str:
        """Collision-proof id: millisecond timestamp + a per-instance counter
        (two creates in the same millisecond would otherwise clash)."""
        self._uid += 1
        return f"{prefix}_{int(datetime.now().timestamp() * 1000)}_{self._uid}"

    def _proven_child_count(self, nid: str) -> int:
        """Number of proven/absolute child narratives that link UP to ``nid``.
        A main narrative is supported by its sub-narratives, so it may be proven
        even with no direct evidence of its own."""
        if not nid:
            return 0
        g = self.load_graph()
        child_ids = {l.get("from") for l in g.get("links", []) if l.get("to") == nid}
        return sum(1 for n in g.get("narratives", [])
                   if n.get("id") in child_ids and n.get("state") in ("proven", "absolute"))

    # ------------------------------------------------------------------ #
    # GEP validation
    # ------------------------------------------------------------------ #
    def _evaluate_gep(self, event: Dict[str, Any]) -> Dict[str, str]:
        """Return {r9, r10, r11} as PASS / FAIL / PARTIAL / N-A for the audit row."""
        actor = event.get("actor", "investigator")
        action = event.get("action", "")
        reason = (event.get("reason") or "").strip()
        refs = event.get("evidence") or []
        kind = event.get("kind", "")

        r9 = "PASS" if reason else "FAIL"

        # R10 only meaningfully applies when a narrative's evidence is at stake.
        if kind == "narrative" and action in ("CREATE", "EDIT", "STATE_CHANGE",
                                              "DETACH", "ATTACH", "MAKE_ABSOLUTE",
                                              "MAKE_BASE", "MARK_NEGATIVE"):
            # For CREATE the narrative doesn't exist yet — read state/evs from the
            # incoming object; otherwise from the current graph node.
            obj = event.get("object") or {}
            n = self._narrative(event.get("id", ""))
            state = (event.get("state")
                     or obj.get("state")
                     or (n.get("state") if n else None)
                     or "open")
            has_ev = (bool(refs) or bool(obj.get("evs")) or bool(n and n.get("evs"))
                      or self._proven_child_count(event.get("id", "")) > 0)
            exempt = (actor == "investigator" and state in ZERO_EVIDENCE_STATES)
            if has_ev:
                r10 = "PASS"
            elif exempt:
                r10 = "PASS"  # sanctioned exemption
            else:
                r10 = "PARTIAL"
        else:
            r10 = "N-A"

        r11 = "PASS" if actor == "eye" else "N-A"
        return {"r9": r9, "r10": r10, "r11": r11}

    def _gep_rules_applied(self, gep: Dict[str, str]) -> Dict[str, str]:
        m = {"PASS": "satisfied", "PARTIAL": "partially_satisfied", "FAIL": "violated", "N-A": "not_applicable"}
        return {"rule_9": m.get(gep["r9"], "n/a"),
                "rule_10": m.get(gep["r10"], "n/a"),
                "rule_11": m.get(gep["r11"], "n/a")}

    # ------------------------------------------------------------------ #
    # Mutation choke point
    # ------------------------------------------------------------------ #
    def commit(self, event: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """The single mutation entry point. Validates GEP, applies the change,
        persists the graph, and seals a hash-chained audit record.

        Returns ``{ok, seal_hash, audit, change, graph?}``. On a hard GEP failure
        (R9) returns ``{ok: False, error, ...}`` and does NOT mutate the graph.
        Best-effort: any internal error returns ``{ok: False, error}``.
        """
        try:
            if isinstance(event, str):
                event = json.loads(event)
        except Exception as e:
            return {"ok": False, "error": f"bad event json: {e}"}
        if not isinstance(event, dict):
            return {"ok": False, "error": "event must be an object"}

        action = event.get("action", "")
        reason = (event.get("reason") or "").strip()

        with self._lock:
            self.load_graph()  # ensure loaded

            # R9 is hard: refuse a reasonless mutation (collapse/expand are view-only
            # and never reach here).
            if not reason:
                return {"ok": False, "error": "GEP R9: a reason is required", "rule": "r9"}

            # Authorship invariant: an Eye narrative may never assert the unsupported.
            blocked = self._enforce_authorship(event)
            if blocked is not None:
                return blocked

            gep = self._evaluate_gep(event)

            # Apply the mutation (best-effort; tolerant of unknown actions).
            try:
                change = self._apply(event)
            except Exception as e:
                self.logger.error(f"narrative-map apply failed: {e}")
                return {"ok": False, "error": f"apply failed: {e}"}

            # Seal FIRST so the chain-of-custody hash can be stamped onto a newly
            # created evidence card before the graph is persisted.
            audit = self._seal(event, gep)
            try:
                if action == "CREATE" and event.get("kind") == "evidence":
                    ev = (self._graph.get("evidence") or {}).get(event.get("id"))
                    if ev is not None and not ev.get("sealed"):
                        # Compact, collision-safe handle into narrative_map_audit.jsonl.
                        ev["sealed"] = (audit.get("hash") or "")[:16]
            except Exception:
                pass
            self._save()

            return {
                "ok": True,
                "seal_hash": audit.get("hash", ""),
                "audit": audit,
                "change": change,
            }

    def _enforce_authorship(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Authorship invariant: the Eye never *asserts* the unsupported.

        An Eye-authored narrative may be ``open`` with no evidence — that is the
        provisional "investigating" state (e.g. a freshly planned sub-question
        theme). What is forbidden is an Eye narrative that *concludes* (``proven``)
        with zero evidence. A checked-and-empty Eye theme is instead recorded as a
        ``negative`` finding (absence IS the finding). Investigator narratives may be
        empty (``needs`` hypothesis / ``absolute`` stipulated fact).

        Returns an error dict to reject, or None to proceed. May mutate ``event``
        (auto-flip a proven theme that lost its last evidence to negative)."""
        if event.get("kind") != "narrative":
            return None
        actor = event.get("actor", "investigator")
        action = event.get("action", "")

        if action == "CREATE":
            obj = event.get("object") or {}
            author = obj.get("authoredBy",
                             f"eye:{self.model_name}" if actor == "eye" else "investigator")
            evs = obj.get("evs") or []
            state = obj.get("state", "open")
            if str(author).startswith("eye") and not evs and state == "proven":
                return {"ok": False, "error":
                        "An Eye narrative cannot be 'proven' with zero evidence (R10). "
                        "Attach evidence, or leave it 'open' while investigating.",
                        "rule": "r10"}
            return None

        n = self._narrative(event.get("id", ""))
        if not n:
            return None
        author = n.get("authoredBy", "")
        if not str(author).startswith("eye"):
            return None  # investigator narratives may be empty (needs/absolute)

        # Evidence count after this change (DETACH removes one).
        evs = list(n.get("evs", []))
        if action == "DETACH":
            eid = event.get("evidenceId") or event.get("from")
            if eid in evs:
                evs.remove(eid)
        target_state = event.get("state", n.get("state"))

        if not evs and target_state == "proven" and self._proven_child_count(n.get("id", "")) == 0:
            # A proven Eye narrative with no evidence AND no proven sub-narrative can
            # no longer assert — record the absence as a negative finding instead.
            # (A main narrative IS allowed to be proven by its proven children.)
            event["action"] = "MARK_NEGATIVE"
            event["state"] = "negative"
            if not event.get("reason"):
                event["reason"] = ("Supporting evidence removed — recorded as a "
                                   "negative finding (absence is the finding).")
        return None

    def _apply(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Mutate the in-memory graph for one event. Returns a compact ``change``
        descriptor for the live UI envelope."""
        g = self._graph
        action = event.get("action", "")
        kind = event.get("kind", "")
        nid = event.get("id", "")
        ids: List[str] = [i for i in [nid] if i]

        def stamp(actor: str) -> str:
            return f"eye:{self.model_name}" if actor == "eye" else "investigator"

        actor = event.get("actor", "investigator")

        if action == "CREATE":
            obj = dict(event.get("object") or {})
            obj.setdefault("authoredBy", stamp(actor))
            if kind == "narrative":
                obj.setdefault("state", "open")
                obj.setdefault("evs", [])
                obj.setdefault("notes", [])
                g["narratives"].append(obj)
                # Auto-link upward: to the PARENT narrative when meta.parent is set
                # (a sub-narrative in the tree), otherwise to the verdict (a root /
                # main narrative). Builds the main → sub → verdict hierarchy.
                parent = (obj.get("meta") or {}).get("parent")
                target = parent if (parent and self._narrative(parent)) else g["verdict"]["id"]
                lid = f"l_{obj.get('id')}"
                if not any(l["from"] == obj.get("id") for l in g["links"]):
                    g["links"].append({"id": lid, "from": obj.get("id"), "to": target})
            elif kind == "evidence":
                obj.setdefault("notes", [])
                g["evidence"][obj["id"]] = obj
                host = event.get("to")
                if host and (n := self._narrative(host)):
                    n["evs"].append(obj["id"])
                    ids.append(host)
                else:
                    obj["free"] = True
            elif kind == "global":
                # Free-floating global card (System Identity, Technical Observation,
                # note). No auto-link — it floats unconnected until linked later.
                obj.setdefault("kicker", "note")
                obj.setdefault("notes", [])
                g.setdefault("globals", []).append(obj)
            ids = [obj.get("id")] + ids

        elif action == "EDIT":
            patch = event.get("patch") or event.get("object") or {}
            if kind == "narrative" and (n := self._narrative(nid)):
                # EDIT owns title/reason only. State changes MUST go through the
                # guarded STATE_CHANGE/MARK_*/MAKE_* path (which enforces the R10
                # authorship rule) — an EDIT must not be able to set state.
                for k in ("title", "reason"):
                    if k in patch:
                        n[k] = patch[k]
                n["authoredBy"] = stamp(actor)
            elif kind == "evidence" and nid in g["evidence"]:
                e = g["evidence"][nid]
                for k in ("kicker", "data", "reason", "ref"):
                    if k in patch:
                        e[k] = patch[k]
                e["authoredBy"] = stamp(actor)
            elif kind == "verdict":
                for k in ("title", "reason"):
                    if k in patch:
                        g["verdict"][k] = patch[k]
                g["verdict"]["authoredBy"] = stamp(actor)
            elif kind == "global":
                gc = next((c for c in g.get("globals", []) if c.get("id") == nid), None)
                if gc is not None:
                    for k in ("kicker", "title", "body"):
                        if k in patch:
                            gc[k] = patch[k]
                    gc["authoredBy"] = stamp(actor)

        elif action in ("STATE_CHANGE", "MARK_NEGATIVE", "MAKE_ABSOLUTE", "MAKE_BASE"):
            new_state = event.get("state")
            if action == "MARK_NEGATIVE":
                new_state = "negative"
            elif action == "MAKE_ABSOLUTE":
                new_state = "absolute"
            elif action == "MAKE_BASE":
                new_state = "needs"
            if kind == "verdict" and new_state in VERDICT_STATES:
                g["verdict"]["state"] = new_state
            elif new_state in STATES and (n := self._narrative(nid)):
                n["state"] = new_state

        elif action == "ATTACH":
            eid = event.get("evidenceId") or event.get("from")
            to = event.get("to") or nid
            # remove from previous owner
            for n in g["narratives"]:
                if eid in n.get("evs", []):
                    n["evs"].remove(eid)
            if eid in g["evidence"]:
                g["evidence"][eid]["free"] = False
            if (n := self._narrative(to)) and eid not in n["evs"]:
                idx = event.get("index")
                if isinstance(idx, int) and 0 <= idx <= len(n["evs"]):
                    n["evs"].insert(idx, eid)
                else:
                    n["evs"].append(eid)
            ids = [to, eid]

        elif action == "DETACH":
            eid = event.get("evidenceId") or event.get("from") or nid
            for n in g["narratives"]:
                if eid in n.get("evs", []):
                    n["evs"].remove(eid)
            if eid in g["evidence"]:
                g["evidence"][eid]["free"] = True
                g["evidence"][eid]["x"] = event.get("x")
                g["evidence"][eid]["y"] = event.get("y")
            ids = [eid]

        elif action == "NOTE":
            note = event.get("note") or {}
            if not note.get("ts"):
                note["ts"] = _utc_now()
            if kind == "narrative" and (n := self._narrative(nid)):
                n.setdefault("notes", []).append(note)
            elif kind == "evidence" and nid in g["evidence"]:
                g["evidence"][nid].setdefault("notes", []).append(note)
            elif kind == "global":
                gc = next((c for c in g.get("globals", []) if c.get("id") == nid), None)
                if gc is not None:
                    gc.setdefault("notes", []).append(note)

        elif action == "LINK":
            # Supports narrative->verdict (default) AND narrative->narrative
            # (pass an explicit `to`). A narrative may not link to itself.
            frm = event.get("from") or nid
            to = event.get("to") or g["verdict"]["id"]
            if frm and to and frm != to and not any(
                    l["from"] == frm and l["to"] == to for l in g["links"]):
                g["links"].append({"id": f"l_{frm}_{to}", "from": frm, "to": to})
            ids = [frm, to]

        elif action == "UNLINK":
            # Remove a single link by id, or by matching from/to.
            link_id = event.get("link_id") or event.get("id")
            frm = event.get("from")
            to = event.get("to")
            before = len(g["links"])
            g["links"] = [
                l for l in g["links"]
                if not (
                    (link_id and l.get("id") == link_id)
                    or (frm and to and l.get("from") == frm and l.get("to") == to)
                )
            ]
            ids = [i for i in (frm, to) if i]
            if len(g["links"]) == before:
                self.logger.debug("UNLINK matched no link (id=%s from=%s to=%s)", link_id, frm, to)

        elif action == "DELETE":
            if kind == "narrative":
                g["narratives"] = [n for n in g["narratives"] if n["id"] != nid]
                # Drop links on EITHER side of the removed narrative.
                g["links"] = [l for l in g["links"] if l["from"] != nid and l["to"] != nid]
            elif kind == "evidence":
                for n in g["narratives"]:
                    if nid in n.get("evs", []):
                        n["evs"].remove(nid)
                g["evidence"].pop(nid, None)
            elif kind == "global":
                g["globals"] = [c for c in g.get("globals", []) if c.get("id") != nid]
                g["links"] = [l for l in g["links"] if l["from"] != nid and l["to"] != nid]

        elif action == "MOVE":
            # Free-form 2D placement: store the card's x/y so its position on the
            # board persists. Works for evidence, narratives, and the verdict.
            if kind == "evidence" and nid in g["evidence"]:
                g["evidence"][nid]["x"] = event.get("x")
                g["evidence"][nid]["y"] = event.get("y")
            elif kind == "narrative":
                n = self._narrative(nid)
                if n is not None:
                    n["x"] = event.get("x")
                    n["y"] = event.get("y")
            elif kind == "verdict":
                g["verdict"]["x"] = event.get("x")
                g["verdict"]["y"] = event.get("y")
            elif kind == "global":
                gc = next((c for c in g.get("globals", []) if c.get("id") == nid), None)
                if gc is not None:
                    gc["x"] = event.get("x")
                    gc["y"] = event.get("y")

        return {"action": action, "kind": kind, "ids": [i for i in ids if i],
                "state": event.get("state")}

    # ------------------------------------------------------------------ #
    # Hash-chained audit seal
    # ------------------------------------------------------------------ #
    def _seal(self, event: Dict[str, Any], gep: Dict[str, str]) -> Dict[str, Any]:
        """Append one hash-chained audit record (EvidenceSeal pattern)."""
        seq = self._seq + 1
        ts = _utc_now()
        actor = event.get("actor", "investigator")
        target = event.get("label") or event.get("id") or event.get("kind") or ""
        reason = (event.get("reason") or "")
        refs = event.get("evidence") or []

        payload = json.dumps(event, sort_keys=True, ensure_ascii=False, default=str)
        payload_sha = _sha256(payload)
        meta = f"{seq}|{ts}|{event.get('action','')}|{actor}|{target}|{reason}|" \
               f"{','.join(refs)}|{gep['r9']}{gep['r10']}{gep['r11']}"
        meta_sha = _sha256(meta)
        prev = self._prev_hash
        seal_hash = _sha256(prev + payload_sha + meta_sha)

        record = {
            "seq": seq,
            "ts": ts,
            "action": event.get("action", ""),
            "actor": actor,
            "kind": event.get("kind", ""),
            "target": str(target),
            # The node id this change applies to, so the Compliance window can
            # deep-link the entry to that Verdict/Narrative/Evidence detail panel.
            "card_id": str(event.get("id") or ""),
            "reason": reason,
            "evidence": refs,
            "gep": gep,
            "gep_rules_applied": self._gep_rules_applied(gep),
            "payload_sha256": payload_sha,
            "metadata_sha256": meta_sha,
            "prevHash": prev,
            "hash": seal_hash,
        }
        wrote = False
        try:
            if self._audit_path:
                self._audit_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                wrote = True
        except Exception as e:
            self.logger.error(f"Could not append narrative-map audit: {e}")
        if wrote or not self._audit_path:
            self._seq = seq
            self._prev_hash = seal_hash
        return record

    def recent_audit(self, limit: int = 200) -> List[Dict[str, Any]]:
        """The most recent audit rows (newest first) for the map's Audit tab and the
        Compliance panel."""
        rows: List[Dict[str, Any]] = []
        try:
            if self._audit_path and self._audit_path.exists():
                with open(self._audit_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                rows.append(json.loads(line))
                            except Exception:
                                continue
        except Exception as e:
            self.logger.debug(f"recent_audit read failed: {e}")
        return rows[-limit:][::-1]

    def verify_chain(self) -> bool:
        """Re-walk the audit log and confirm the hash chain is intact end-to-end.

        Tamper-evident over the visible content too: the metadata hash is RECOMPUTED
        from each record's fields (action/actor/target/reason/evidence/gep), so
        editing a human-readable field like ``reason`` breaks the chain even though
        the stored ``metadata_sha256`` was not touched. An empty/missing log is
        vacuously valid."""
        try:
            if not self._audit_path or not self._audit_path.exists():
                return True
            prev = ""
            with open(self._audit_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    s = json.loads(line)
                    gep = s.get("gep", {}) or {}
                    meta = (f"{s.get('seq','')}|{s.get('ts','')}|{s.get('action','')}|"
                            f"{s.get('actor','')}|{s.get('target','')}|{s.get('reason','')}|"
                            f"{','.join(s.get('evidence', []) or [])}|"
                            f"{gep.get('r9','')}{gep.get('r10','')}{gep.get('r11','')}")
                    meta_sha = _sha256(meta)
                    if s.get("metadata_sha256", "") != meta_sha:
                        return False
                    expected = _sha256(prev + s.get("payload_sha256", "") + meta_sha)
                    if s.get("prevHash", "") != prev or s.get("hash") != expected:
                        return False
                    prev = s.get("hash", "")
            return True
        except Exception as e:
            self.logger.warning(f"narrative-map verify_chain failed: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Eye-side mutations (used by the agentic loop)
    # ------------------------------------------------------------------ #
    def sync_from_plan(self, sub_questions: List[Dict[str, str]],
                       model: Optional[str] = None) -> List[Dict[str, Any]]:
        """Full auto-sync: upsert one provisional ``open`` narrative per decomposed
        sub-question ("a claim to prove"). Idempotent by title — an existing
        narrative with the same title is not duplicated. Returns the commit results
        (so the caller can emit live updates). Best-effort; never raises."""
        results: List[Dict[str, Any]] = []
        try:
            g = self.load_graph()
            existing = {(n.get("title") or "").strip().lower() for n in g["narratives"]}
            for i, sq in enumerate(sub_questions or []):
                if isinstance(sq, dict):
                    q = (sq.get("q") or sq.get("question") or "").strip()
                    why = (sq.get("why") or "").strip()
                else:
                    q, why = str(sq).strip(), ""
                if not q or q.lower() in existing:
                    continue
                nid = f"n_sq_{int(datetime.now().timestamp()*1000)}_{i}"
                ev = {
                    "action": "CREATE",
                    "actor": "eye",
                    "kind": "narrative",
                    "id": nid,
                    "label": q[:60],
                    "reason": why or "Sub-question to prove against the case artifacts.",
                    "evidence": [],
                    "object": {
                        "id": nid,
                        "state": "open",
                        "title": q[:200],
                        "reason": why or "Sub-question raised during investigation planning.",
                        "authoredBy": f"eye:{model or self.model_name}",
                        "evs": [],
                        "notes": [],
                    },
                }
                results.append(self.commit(ev))
                existing.add(q.lower())
        except Exception as e:
            self.logger.debug(f"sync_from_plan skipped: {e}")
        return results

    def attach_evidence(self, narrative_title_or_id: str, evidence: Dict[str, Any],
                        model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create an evidence card and attach it to a narrative (by id or title),
        flipping an ``open`` narrative to ``proven``. Best-effort; returns the
        commit result or None."""
        try:
            n = self._narrative(narrative_title_or_id)
            if not n:
                t = (narrative_title_or_id or "").strip().lower()
                n = next((x for x in self.load_graph()["narratives"]
                          if (x.get("title") or "").strip().lower() == t), None)
            if not n:
                return None
            eid = evidence.get("id") or self._new_id("e")
            obj = {
                "id": eid,
                "kicker": evidence.get("kicker", "artifact"),
                "data": evidence.get("data", ""),
                "content": evidence.get("content", ""),
                "reason": evidence.get("reason", "Supports the narrative."),
                "ref": evidence.get("ref", ""),
                # SQL + database that produced this evidence, so the map's detail
                # window can reload the actual source rows on demand.
                "query": evidence.get("query", ""),
                "database": evidence.get("database", ""),
                "authoredBy": f"eye:{model or self.model_name}",
                "sealed": evidence.get("sealed"),
                "notes": [],
                "free": False,
            }
            res = self.commit({
                "action": "CREATE", "actor": "eye", "kind": "evidence", "id": eid,
                "label": obj["data"][:60], "reason": obj["reason"],
                "evidence": [obj["ref"]] if obj["ref"] else [],
                "object": obj, "to": n["id"],
            })
            if n.get("state") == "open":
                self.set_state(n["id"], "proven",
                               reason="Supporting evidence attached.", model=model)
            return res
        except Exception as e:
            self.logger.debug(f"attach_evidence skipped: {e}")
            return None

    def set_state(self, narrative_id: str, state: str, reason: str = "",
                  model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Eye-side state flip (e.g. open -> proven / negative)."""
        if state not in STATES:
            return None
        try:
            return self.commit({
                "action": "STATE_CHANGE", "actor": "eye", "kind": "narrative",
                "id": narrative_id, "label": narrative_id, "state": state,
                "reason": reason or f"State updated to {state} during investigation.",
                "evidence": [],
            })
        except Exception as e:
            self.logger.debug(f"set_state skipped: {e}")
            return None

    def set_verdict(self, title: str, reason: str = "",
                    model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Eye-side authoring of the case Verdict — a meaningful, self-describing
        conclusion synthesized from the proven narratives. Routed through the same
        EDIT/verdict commit path the investigator uses, so it stays editable.
        Best-effort; returns the commit result or None."""
        title = (title or "").strip()
        if not title:
            return None
        try:
            return self.commit({
                "action": "EDIT", "actor": "eye", "kind": "verdict",
                "id": self.load_graph()["verdict"]["id"], "label": title[:60],
                "reason": (reason or "Synthesized from the proven narratives.").strip(),
                "evidence": [],
                "patch": {"title": title, "reason": reason or ""},
            })
        except Exception as e:
            self.logger.debug(f"set_verdict skipped: {e}")
            return None

    def set_verdict_state(self, state: str, reason: str = "",
                          model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Set the verdict lifecycle state: ``open`` (still under investigation),
        ``proven``, or ``unproven``. Routed through the guarded STATE_CHANGE path."""
        if state not in VERDICT_STATES:
            return None
        try:
            return self.commit({
                "action": "STATE_CHANGE", "actor": "eye", "kind": "verdict",
                "id": self.load_graph()["verdict"]["id"], "label": f"verdict:{state}",
                "state": state,
                "reason": reason or f"Verdict marked {state}.",
                "evidence": [],
            })
        except Exception as e:
            self.logger.debug(f"set_verdict_state skipped: {e}")
            return None

    def upsert_global(self, kicker: str, title: str, body: str = "",
                      card_id: Optional[str] = None,
                      model: Optional[str] = None) -> Optional[str]:
        """Create (or update) a floating GLOBAL card — System Identity, Technical
        Observations, or a free note. Unconnected by default; the investigator or the
        Eye can link it to a narrative/verdict later. Idempotent when ``card_id`` is
        supplied (re-running the triage updates the same card, not a duplicate).
        Returns the card id, or None."""
        title = (title or "").strip()
        if not title:
            return None
        try:
            g = self.load_graph()
            existing = None
            if card_id:
                existing = next((c for c in g.get("globals", []) if c.get("id") == card_id), None)
            if existing:
                self.commit({
                    "action": "EDIT", "actor": "eye", "kind": "global", "id": card_id,
                    "label": title[:60], "reason": "Updated global observation from triage.",
                    "evidence": [], "patch": {"kicker": kicker, "title": title, "body": body},
                })
                return card_id
            gid = card_id or self._new_id("g")
            self.commit({
                "action": "CREATE", "actor": "eye", "kind": "global", "id": gid,
                "label": title[:60], "reason": "Recorded a global observation.",
                "evidence": [],
                "object": {"id": gid, "kicker": kicker, "title": title, "body": body,
                           "authoredBy": f"eye:{self.model_name}"},
            })
            return gid
        except Exception as e:
            self.logger.debug(f"upsert_global skipped: {e}")
            return None

    def remove_narratives_by_title(self, titles, model: Optional[str] = None) -> int:
        """Delete any narrative whose title matches one of ``titles`` (case-insensitive),
        along with its links — used to dedupe triage observations (System Identity /
        Immediate Technical Observations) that are surfaced as floating GLOBAL cards,
        so the verdict-linked seed copy is removed. Returns the count removed.
        Best-effort; routed through the audited commit/DELETE path."""
        try:
            want = {str(t).strip().lower() for t in (titles or []) if str(t).strip()}
            if not want:
                return 0
            g = self.load_graph()
            victims = [n for n in g.get("narratives", [])
                       if (n.get("title") or "").strip().lower() in want]
            removed = 0
            for n in victims:
                res = self.commit({
                    "action": "DELETE", "actor": "eye", "kind": "narrative", "id": n.get("id"),
                    "label": (n.get("title") or "")[:60],
                    "reason": "Deduped — surfaced as a floating global card, not a verdict narrative.",
                    "evidence": [],
                })
                if res:
                    removed += 1
            return removed
        except Exception as e:
            self.logger.debug(f"remove_narratives_by_title skipped: {e}")
            return 0

    def upsert_finding_narrative(self, title: str, reason: str, question: str,
                                 evidence: Optional[List[Dict[str, Any]]] = None,
                                 state: str = "proven",
                                 model: Optional[str] = None,
                                 parent: Optional[str] = None) -> Optional[str]:
        """Create (or update) a narrative that represents a FINDING.

        The card title is the finding/claim; the originating ``question`` is stored
        only as ``meta.created_from`` (never the title). Idempotent by that metadata
        — a later finding for the same question updates the existing narrative
        instead of duplicating it. Returns the narrative id, or None.

        Authorship rule (R10): an Eye narrative may not be created ``proven`` with
        zero evidence, so a supported finding is created ``open`` and flipped to
        ``proven`` by attaching its evidence; an unsupported one is recorded
        ``negative`` (absence is the finding)."""
        title = (title or "").strip()
        if not title:
            return None
        if state not in STATES:
            state = "proven"
        evidence = evidence or []
        try:
            existing = self._narrative_by_created_from(question)
            if existing:
                nid = existing["id"]
                self.commit({
                    "action": "EDIT", "actor": "eye", "kind": "narrative", "id": nid,
                    "label": title[:60],
                    "reason": reason or existing.get("reason") or "Established finding.",
                    "evidence": [], "patch": {"title": title, "reason": reason or ""},
                })
            else:
                nid = self._new_id("n_find")
                # Supported → start 'open' (attach flips to proven). Unsupported
                # proven request → record as 'negative'. Explicit negative stays.
                create_state = "open" if evidence else ("negative" if state in ("proven", "negative") else state)
                meta = {"created_from": (question or "").strip()}
                if parent:
                    meta["parent"] = parent  # link this finding UNDER its main narrative
                obj = {
                    "id": nid, "state": create_state, "title": title,
                    "reason": reason or "Established finding.",
                    "authoredBy": f"eye:{model or self.model_name}",
                    "evs": [], "notes": [],
                    "meta": meta,
                }
                self.commit({
                    "action": "CREATE", "actor": "eye", "kind": "narrative", "id": nid,
                    "label": title[:60], "reason": obj["reason"], "evidence": [], "object": obj,
                })
            for ev in evidence:
                self.attach_evidence(nid, ev, model=model)  # flips open -> proven
            if not evidence and state == "negative":
                self.set_state(nid, "negative",
                               reason=reason or "Checked — nothing established.", model=model)
            return nid
        except Exception as e:
            self.logger.debug(f"upsert_finding_narrative skipped: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Context injection — Tier A (overview) + Tier B (relevant slice)
    # ------------------------------------------------------------------ #
    _STATE_HINT = {
        "proven": "established by evidence",
        "open": "investigating",
        "negative": "checked — nothing found",
        "needs": "⚠ hypothesis (no evidence yet)",
        "absolute": "established (stipulated fact)",
    }

    def overview_block(self, max_chars: int = 3000) -> str:
        """Tier A — a compact ``## Case Memory`` overview injected once per turn.

        One line per narrative (state + title + state hint) plus the verdict; flags
        any narrative carrying investigator notes so the Eye knows to consult Tier B.
        Returns '' when the map is empty so the prompt stays clean."""
        try:
            g = self.load_graph()
            narratives = g.get("narratives") or []
            verdict = g.get("verdict") or {}
            if not narratives and not (verdict.get("title") and verdict.get("reason")):
                return ""

            order = {"proven": 0, "open": 1, "absolute": 2, "needs": 3, "negative": 4}
            narratives = sorted(narratives, key=lambda n: order.get(n.get("state"), 5))

            lines = [
                "## Case Memory (Narrative Map — your persistent working memory)",
                "Treat this as authoritative: what has been proven, what is still open, "
                "and any investigator-stipulated facts/notes. Do not re-derive proven "
                "items; honor investigator notes and `absolute` narratives.",
                f"VERDICT → {verdict.get('title','(none)')}"
                + (f" — {verdict.get('reason')}" if verdict.get("reason") else ""),
            ]
            for n in narratives:
                state = n.get("state", "open")
                ev_n = len(n.get("evs") or [])
                note_n = len(n.get("notes") or [])
                hint = self._STATE_HINT.get(state, "")
                flags = f" · {ev_n} evidence" if ev_n else ""
                if state == "needs" and not ev_n:
                    flags = " · ⚠ hypothesis"
                if note_n:
                    flags += " · 📝note"
                lines.append(f"[{state.upper()}] {n.get('title','')} — {hint}{flags}")
            block = "\n".join(lines)
            if len(block) > max_chars:
                block = block[:max_chars].rsplit("\n", 1)[0] + "\n… (truncated)"
            return block
        except Exception as e:
            self.logger.debug(f"overview_block skipped: {e}")
            return ""

    def relevant_slice(self, sub_question: str, max_narratives: int = 3,
                       max_chars: int = 1200) -> str:
        """Tier B — expand ONLY the narratives/evidence whose keywords overlap this
        sub-question, INCLUDING full investigator note text verbatim, so human
        guidance reaches the model. Returns '' when nothing overlaps."""
        try:
            g = self.load_graph()
            narratives = g.get("narratives") or []
            evidence = g.get("evidence") or {}
            if not narratives:
                return ""
            q_tokens = _tokenize(sub_question)
            if not q_tokens:
                return ""

            scored = []
            for n in narratives:
                text = (n.get("title", "") + " " + n.get("reason", "") + " "
                        + " ".join(str(x.get("text", "")) for x in (n.get("notes") or [])))
                ov = len(q_tokens & _tokenize(text))
                if ov > 0:
                    scored.append((ov, n))
            scored.sort(key=lambda x: x[0], reverse=True)
            if not scored:
                return ""

            out = ["### Related Case Memory (from the Narrative Map)"]
            for _, n in scored[:max_narratives]:
                out.append(f"- [{n.get('state','open').upper()}] {n.get('title','')}"
                           + (f" — {n.get('reason')}" if n.get("reason") else ""))
                for eid in (n.get("evs") or [])[:3]:
                    e = evidence.get(eid)
                    if e:
                        out.append(f"    • evidence ({e.get('kicker','')}): {e.get('data','')}"
                                   + (f"  [{e.get('ref')}]" if e.get("ref") else ""))
                for note in (n.get("notes") or []):
                    by = note.get("by", "investigator")
                    label = "Investigator note" if by in ("investigator", "human") else (
                        "Eye note" if by == "eye" else "System note")
                    out.append(f'    📝 {label}: "{note.get("text","")}"')
            block = "\n".join(out)
            if len(block) > max_chars:
                block = block[:max_chars].rsplit("\n", 1)[0] + "\n… (truncated)"
            return block
        except Exception as e:
            self.logger.debug(f"relevant_slice skipped: {e}")
            return ""


__all__ = ["NarrativeMapService", "STATES", "ACTIONS"]
