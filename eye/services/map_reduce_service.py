"""
MapReduceService — analyze a WHOLE large artifact without dropping evidence.

You cannot feed a 50 MB parsed MFT (or a huge batch of LNK/USN rows) into one
context window. Instead of silently truncating, this service:

  MAP    — packs every row into chunks that each fit under a token budget,
           sends each chunk to the model ("find anomalies in this batch"),
           and SEALS each chunk payload (chain of custody).
  REDUCE — synthesizes all per-batch findings into one consolidated analysis
           (recursively, if the summaries themselves overflow).

Guarantees: every row lands in exactly one chunk; nothing is split or dropped
silently; a single row that cannot fit a chunk triggers a HARD refusal (the
investigator must select fewer columns / narrow the query).
"""

import json
import logging
from typing import Any, Dict, List, Optional, Callable

from eye.services.evidence_seal import EvidenceSeal


class MapReduceService:
    def __init__(self, context_manager):
        self.cm = context_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    def _base_system_prompt(self) -> str:
        try:
            return self.cm._build_system_prompt("", [])
        except Exception:
            return "You are EYE, a precise Windows forensic analyst. Be specific and never invent data."

    def _max_ctx(self) -> int:
        return int(getattr(self.cm, "max_total_tokens", 8192) or 8192)

    def analyze(
        self,
        database_name: str,
        sql_query: str,
        instruction: str,
        chunk_token_budget: int = 3000,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        tc = self.cm.token_counter
        model = self.cm.model_router.config.get("model_name", "LLM")
        # Shared single writer owned by the ContextManager — using the same
        # instance as the main query loop keeps one hash chain per case dir
        # (two writers would fork it).
        seal = self.cm.evidence_seal

        res = self.cm.database_service.execute_query(database_name, sql_query)
        if not res.get("success"):
            return {"success": False, "error": f"Query failed: {res.get('error')}"}
        rows = res.get("data") or res.get("rows") or []
        if not rows:
            return {"success": True, "summary": "No rows matched the query — nothing to analyze.",
                    "chunks_processed": 0, "rows_analyzed": 0}

        # ---- Pack rows into chunks (fail hard if a single row won't fit) ----
        chunks: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        current_tokens = 0
        for idx, row in enumerate(rows):
            row_tokens = tc.count_tokens(json.dumps(row, default=str))
            if row_tokens > chunk_token_budget:
                return {
                    "success": False,
                    "error": (
                        f"Row {idx} alone is {row_tokens} tokens, larger than the per-chunk "
                        f"budget of {chunk_token_budget}. Refusing to split a single evidence "
                        "record across chunks. Select fewer/narrower columns or raise the budget."
                    ),
                }
            if current and current_tokens + row_tokens > chunk_token_budget:
                chunks.append(current)
                current, current_tokens = [], 0
            current.append({"_row_index": idx, **row})
            current_tokens += row_tokens
        if current:
            chunks.append(current)

        n = len(chunks)
        sysp = self._base_system_prompt()
        summaries: List[str] = []

        for ci, chunk in enumerate(chunks):
            if progress:
                try:
                    progress(ci + 1, n)
                except Exception:
                    pass
            first_idx, last_idx = chunk[0]["_row_index"], chunk[-1]["_row_index"]
            rows_text = json.dumps(chunk, default=str, indent=2)
            map_prompt = (
                f"You are analyzing batch {ci + 1} of {n} from forensic database '{database_name}'.\n"
                f"INSTRUCTION: {instruction}\n\n"
                "List ONLY notable findings/anomalies in THIS batch as concise bullets with the "
                "specific record index/timestamp/path. If nothing is notable, reply exactly "
                "'No anomalies in this batch.'\n\n"
                f"RECORDS (rows {first_idx}-{last_idx}):\n{rows_text}"
            )
            payload = f"<<SYSTEM>>\n{sysp}\n<<USER>>\n{map_prompt}"
            seal.seal(
                payload, phase="mapreduce_map", iteration=ci + 1, query=instruction,
                model=model, max_context=self._max_ctx(), token_count=tc.count_tokens(payload),
                evidence_refs=[{
                    "tool": "analyze_large_dataset", "database": database_name, "sql": sql_query,
                    "row_index_range": [first_idx, last_idx], "row_count": len(chunk),
                }],
            )
            try:
                resp = self.cm.model_router.generate(system_prompt=sysp, user_message=map_prompt, tools=[], history=[])
            except Exception as e:
                self.logger.error(f"Map step {ci+1}/{n} failed: {e}")
                return {"success": False, "error": f"Map step {ci+1}/{n} failed: {e}",
                        "chunks_processed": ci, "rows_analyzed": last_idx + 1}
            summaries.append(f"Batch {ci + 1} (rows {first_idx}-{last_idx}): " + (resp.get("content") or "").strip())

        final_summary = self._reduce(summaries, instruction, database_name, sql_query,
                                     len(rows), seal, model, tc, sysp, chunk_token_budget)
        return {
            "success": True,
            "summary": final_summary,
            "chunks_processed": n,
            "rows_analyzed": len(rows),
            "database": database_name,
            "note": f"Full artifact analyzed in {n} sealed batch(es); every row covered exactly once.",
        }

    def _reduce(self, summaries, instruction, database_name, sql_query, total_rows,
                seal, model, tc, sysp, chunk_token_budget) -> str:
        """Synthesize batch summaries. If the joined summaries themselves exceed
        the budget, reduce them hierarchically (reduce-of-reduces) so even a huge
        number of batches never silently drops findings."""
        joined = "\n".join(summaries)
        reduce_prompt = (
            f"You analyzed {total_rows} forensic records from '{database_name}' in "
            f"{len(summaries)} batches.\nINSTRUCTION: {instruction}\n\n"
            "Synthesize the per-batch findings below into ONE consolidated, chronological "
            "forensic analysis citing specific records/timestamps. Do not invent data.\n\n"
            f"BATCH FINDINGS:\n{joined}"
        )
        payload = f"<<SYSTEM>>\n{sysp}\n<<USER>>\n{reduce_prompt}"
        usable = self._max_ctx() - max(512, int(self._max_ctx() * 0.1))

        if tc.count_tokens(payload) > usable and len(summaries) > 1:
            # Hierarchical reduce: group the summaries and reduce each group first.
            groups: List[List[str]] = []
            cur, cur_tok = [], 0
            for s in summaries:
                st = tc.count_tokens(s)
                if cur and cur_tok + st > chunk_token_budget:
                    groups.append(cur); cur, cur_tok = [], 0
                cur.append(s); cur_tok += st
            if cur:
                groups.append(cur)
            intermediate = [
                self._reduce(g, instruction, database_name, sql_query, total_rows,
                             seal, model, tc, sysp, chunk_token_budget)
                for g in groups
            ]
            return self._reduce(intermediate, instruction, database_name, sql_query,
                                total_rows, seal, model, tc, sysp, chunk_token_budget)

        seal.seal(
            payload, phase="mapreduce_reduce", iteration=0, query=instruction,
            model=model, max_context=self._max_ctx(), token_count=tc.count_tokens(payload),
            evidence_refs=[{"tool": "analyze_large_dataset", "database": database_name,
                            "sql": sql_query, "row_count": total_rows, "batches": len(summaries)}],
        )
        try:
            final = self.cm.model_router.generate(system_prompt=sysp, user_message=reduce_prompt, tools=[], history=[])
            return (final.get("content") or "").strip()
        except Exception as e:
            self.logger.error(f"Reduce step failed: {e}")
            return "Reduce step failed: " + str(e) + "\n\nRaw batch findings:\n" + joined
