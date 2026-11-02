"""Run Eye on a set of gold forensic questions and score the answers.

    python -m eye.evals.run_eval --questions "../eye-evals/eyecase.yaml" \
        --case <case_dir> --backend claude_code --model haiku --effort medium \
        --out eval_haiku.jsonl [--only id1,id2] [--in-place]

Eye runs exactly as in the app (ContextManager.process_query, the whole
investigation loop) on one conversation, so a follow-up question sees the
earlier answers. The case is copied to a temporary folder first, because Eye
writes its logs and report into the case; --in-place skips the copy.

Per question it records the answer, the score (scoring.py), model calls,
tokens (sent / cache read / cache write / out), seconds and tools used, and it
prints a summary table at the end. The gold YAML is kept outside the repo: it
holds case data.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _answer_text(result) -> str:
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return result
    if isinstance(result, dict):
        data = result.get("data") if isinstance(result.get("data"), dict) else None
        for src in (result, data or {}):
            for key in ("response", "content", "answer"):
                if isinstance(src.get(key), str):
                    return src[key]
    return str(result or "")


def _usage_of(reply, backend) -> dict:
    u = (reply or {}).get("usage") if isinstance(reply, dict) else None
    if isinstance(u, dict):
        return u
    lu = getattr(backend, "last_usage", None)
    if lu is None:
        return {}
    get = (lambda k: lu.get(k)) if isinstance(lu, dict) else (lambda k: getattr(lu, k, None))
    return {"input_tokens": get("input_tokens") or 0, "output_tokens": get("output_tokens") or 0,
            "cache_read_input_tokens": get("cache_read_input_tokens") or 0,
            "cache_creation_input_tokens": get("cache_creation_input_tokens") or 0}


def build_context(case_dir, config):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from eye.services.credential_manager import CredentialManager
    from eye.services.model_router import ModelRouter
    from eye.services.database_service import ForensicDatabaseService
    from eye.services.search_service import ForensicSearchService
    from eye.services.rag_service import RAGService
    from eye.services.report_engine import ReportEngine
    from eye.services.case_context_manager import CaseContextManager
    from eye.services.context_manager import ContextManager
    router = ModelRouter(config=config, credential_manager=CredentialManager())
    arts = os.path.join(case_dir, "Target_Artifacts")
    ctx = ContextManager(model_router=router, database_service=ForensicDatabaseService(arts),
                         search_service=ForensicSearchService(arts),
                         rag_service=RAGService(embedding_client=None),
                         report_engine=ReportEngine(case_dir), case_directory=case_dir,
                         case_context_manager=CaseContextManager(case_dir))
    return ctx, router


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--questions", required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--backend", default="claude_code")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--effort", default=None)
    ap.add_argument("--integration", default=None, help="integration_type (inferred when omitted)")
    ap.add_argument("--endpoint", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the case copy (Eye's logs) for inspection")
    a = ap.parse_args(argv)

    import yaml
    from eye.evals.scoring import score
    with open(a.questions, encoding="utf-8") as fh:
        gold = yaml.safe_load(fh)
    questions = gold["questions"]
    if a.only:
        keep = {x.strip() for x in a.only.split(",") if x.strip()}
        questions = [q for q in questions if q["id"] in keep]

    work = a.case
    tmp = None
    if not a.in_place:
        tmp = tempfile.mkdtemp(prefix="eye_eval_")
        work = os.path.join(tmp, os.path.basename(os.path.normpath(a.case)))
        shutil.copytree(a.case, work)

    from PyQt5 import QtWidgets  # noqa: F401  (Qt objects need an app)
    from PyQt5 import QtWebEngineWidgets  # noqa: F401
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841

    config = {"backend": a.backend, "model_name": a.model}
    if a.integration:
        config["integration_type"] = a.integration
    if a.effort:
        config["effort"] = a.effort
    if a.endpoint:
        config["api_endpoint"] = a.endpoint
    if a.backend == "claude_code":
        config.setdefault("integration_type", "local_cli")
        config["executable_path"] = ""
    ctx, router = build_context(work, config)

    calls = []
    real = router.backend.generate

    def counted(*args, **kw):
        reply = real(*args, **kw)
        u = _usage_of(reply, router.backend)
        calls.append({"usage": u,
                      "tools": [c.get("function", {}).get("name") for c in (reply or {}).get("tool_calls", [])]
                      if isinstance(reply, dict) else []})
        return reply

    router.backend.generate = counted
    rows = []
    try:
        for q in questions:
            calls.clear()
            t = time.perf_counter()
            err = None
            try:
                result = ctx.process_query(q["q"], status_callback=lambda s: None,
                                           hitl_callback=lambda *x, **k: True)
            except Exception as e:  # recorded, the run goes on
                result, err = None, "%s: %s" % (type(e).__name__, e)
            answer = _answer_text(result)
            s = score(q, answer)
            cc = getattr(getattr(ctx, "query_processor", None), "last_claim_check", None) or {}
            tot = lambda k: sum(int(c["usage"].get(k) or 0) for c in calls)  # noqa: E731
            rec = {"id": q["id"], "question": q["q"], "passed": s["passed"], "facts": s["facts"],
                   "missing": s["missing"], "wrong": s["wrong"], "unknown_ok": s["unknown_ok"],
                   "seconds": round(time.perf_counter() - t, 1), "calls": len(calls),
                   "sent": tot("input_tokens") + tot("cache_creation_input_tokens"),
                   "cache_read": tot("cache_read_input_tokens"), "cache_write": tot("cache_creation_input_tokens"),
                   "out": tot("output_tokens"), "cost_usd": round(sum(float(c["usage"].get("cost_usd") or 0)
                                                                      for c in calls), 4),
                   "tools": sorted({n for c in calls for n in c["tools"] if n}),
                   "claims_checked": cc.get("checked", 0),
                   "claims_unsupported": [c.get("value") for c in cc.get("unsupported") or []],
                   "claims_shifted": [[c.get("value"), c.get("shift_hours")] for c in cc.get("shifted") or []],
                   "error": err, "answer": answer,
                   "backend": a.backend, "model": a.model, "effort": a.effort}
            rows.append(rec)
            with open(a.out, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            print("%-24s %-4s facts %.2f  %3d calls  %6.0f s  $%.2f%s" % (
                q["id"], "PASS" if s["passed"] else "fail", s["facts"], rec["calls"], rec["seconds"],
                rec["cost_usd"], ("  missing: %s" % s["missing"]) if s["missing"] else ""), flush=True)
    finally:
        closer = getattr(router.backend, "close_sessions", None)
        if closer:
            closer()
        if tmp and not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        elif tmp:
            print("case copy kept at", work)

    n = len(rows)
    if n:
        print("\n%d/%d passed, mean facts %.2f, %d calls, %.0f s, list-price value $%.2f" % (
            sum(r["passed"] for r in rows), n, sum(r["facts"] for r in rows) / n,
            sum(r["calls"] for r in rows), sum(r["seconds"] for r in rows), sum(r["cost_usd"] for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
