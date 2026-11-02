"""
Backend doctor: checks the Eye's model setup end to end, says what is wrong in words the
investigator can act on, and offers the fix.

The Eye talks to twenty backends of three kinds - command-line tools (Claude Code, Gemini
CLI, llama.cpp ...), local servers (Ollama, LM Studio, vLLM) and cloud APIs (Anthropic,
OpenAI, Gemini, OpenRouter ...). Each fails in its own way: a CLI that is not installed, a
server that is not running, a key that is missing or belongs to another provider, a model
name with a typo ("opuse"), a model the provider has retired. Before this, all of those
arrived as one generic "backend unreachable".

``diagnose(router, credential_manager)`` runs the checks in order and returns a report:

    {"ok": bool, "summary": str, "backend": ..., "model": ..., "seconds": float,
     "checks": [{"id", "title", "status": ok|warn|fail|skip, "detail", "fix"}]}

A ``fix`` is ``{"action", "label", "value"}``; ``apply_fix`` performs the safe ones
(set_model, set_effort) on the live router, and the UI handles the rest (open_setup,
retry). Nothing is changed without the investigator choosing it. Checks never print or
return a key, only whether one is stored and whether it looks like the provider's.

Runs network checks, so call it off the GUI thread (EYEBridge.run_backend_doctor does).
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"

# What a provider's key looks like. A key pasted into the wrong provider (an OpenAI key
# under Anthropic) is the commonest setup mistake and is visible without a request.
KEY_PREFIXES = {
    "anthropic": ("sk-ant-",),
    "openai": ("sk-",),
    "openrouter": ("sk-or-",),
    "gemini": ("AIza",),
    "groq": ("gsk_",),
    "xai": ("xai-",),
    "grok": ("xai-",),
    "nvidia": ("nvapi-",),
}

# Where each provider's keys are made, for the "no key stored" fix.
KEY_PAGES = {
    "anthropic": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
    "gemini": "https://aistudio.google.com/app/apikey",
    "openrouter": "https://openrouter.ai/keys",
    "groq": "https://console.groq.com/keys",
    "mistral": "https://console.mistral.ai/api-keys",
    "xai": "https://console.x.ai",
    "grok": "https://console.x.ai",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "kimi": "https://platform.moonshot.ai/console/api-keys",
    "moonshot": "https://platform.moonshot.ai/console/api-keys",
    "nvidia": "https://build.nvidia.com",
}

# How to get each command-line tool, when it is not found.
CLI_INSTALL = {
    "claude_code": "npm install -g @anthropic-ai/claude-code, then run `claude` once to sign in",
    "codex_cli": "npm install -g @openai/codex, then run `codex` once to sign in",
    "gemini_cli": "npm install -g @google/gemini-cli, then run `gemini` once to sign in "
                  "(Google retired the free individual tier in 2026: use the Gemini API backend instead)",
    "ollama_cli": "install Ollama from ollama.com",
    "llama": "install llama.cpp and put llama-cli on PATH",
    "gpt_cli": "install aichat (cargo install aichat or a release from GitHub)",
    "jules_cli": "install the Jules CLI and sign in",
}

# Model names a CLI accepts besides full ids. Claude Code takes the family aliases.
CLI_MODEL_ALIASES = {
    "claude_code": ["opus", "sonnet", "haiku", "opusplan", "default",
                    "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"],
}

# Where a local server answers, and the path that lists its models.
SERVER_PROBES = {
    "ollama": ("http://localhost:11434", "/api/tags"),
    "lm_studio": ("http://localhost:1234/v1", "/models"),
    "vllm": ("http://localhost:8000/v1", "/models"),
}


def credential_key_for(backend: str) -> str:
    b = (backend or "").lower()
    if b == "moonshot":
        return "kimi_api_key"
    if b == "grok":
        return "xai_api_key"
    return "%s_api_key" % b


def _check(cid, title, status, detail, fix=None) -> Dict[str, Any]:
    detail = (detail or "").replace("?.", "?")
    return {"id": cid, "title": title, "status": status, "detail": detail, "fix": fix}


def _closest(name: str, candidates: List[str]) -> Optional[str]:
    name = (name or "").strip().lower()
    if not name or not candidates:
        return None
    hit = difflib.get_close_matches(name, [c.lower() for c in candidates], n=1, cutoff=0.6)
    if not hit:
        return None
    for c in candidates:
        if c.lower() == hit[0]:
            return c
    return None


def _http_get(url: str, timeout: float = 3.0) -> int:
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:      # nosec - local endpoints
        return r.status


def diagnose(router, credential_manager=None, connect: bool = True, answer: bool = False) -> Dict[str, Any]:
    """Every check for the router's configured backend, in the order a person would fix
    them. ``connect=False`` skips the network checks (for a quick look). ``answer=True``
    also sends one tiny real request: the free connection check passes on an account
    with no credit or no quota left, and only a real request finds that."""
    t0 = time.perf_counter()
    cfg = dict(getattr(router, "config", None) or {})
    backend = (cfg.get("backend") or "").strip()
    model = (cfg.get("model_name") or "").strip()
    checks: List[Dict[str, Any]] = []
    stop = False

    # 1. a backend the Eye knows
    try:
        from eye.backends.backend_registry import SUPPORTED_BACKENDS, integration_type_for
    except Exception:                                           # pragma: no cover
        SUPPORTED_BACKENDS, integration_type_for = [], (lambda b: cfg.get("integration_type") or "")
    if not backend:
        checks.append(_check("backend", "Model provider chosen", FAIL,
                             "No model provider is set up yet.",
                             {"action": "open_setup", "label": "Set up a model"}))
        stop = True
    elif SUPPORTED_BACKENDS and backend not in SUPPORTED_BACKENDS:
        near = _closest(backend, SUPPORTED_BACKENDS)
        checks.append(_check("backend", "Model provider chosen", FAIL,
                             "'%s' is not a provider the Eye knows%s." % (
                                 backend, " - did you mean '%s'?" % near if near else ""),
                             {"action": "open_setup", "label": "Choose a provider"}))
        stop = True
    else:
        kind = cfg.get("integration_type") or integration_type_for(backend)
        checks.append(_check("backend", "Model provider chosen", OK, "%s (%s)" % (backend, kind)))

    # 2. a model name
    if not stop:
        if not model:
            checks.append(_check("model", "Model chosen", FAIL, "No model is chosen for %s." % backend,
                                 {"action": "open_setup", "label": "Choose a model"}))
            stop = True
        else:
            checks.append(_check("model", "Model chosen", OK, model))

    kind = (cfg.get("integration_type") or "") if not stop else ""
    if not stop and not kind:
        try:
            kind = integration_type_for(backend)
        except Exception:
            kind = ""

    # 3. what this kind of backend needs before it can answer
    if not stop and kind == "cloud_api" and credential_manager is None:
        checks.append(_check("key", "API key stored", SKIP, "Not checked here."))
    elif not stop and kind == "cloud_api":
        key_name = credential_key_for(backend)
        key = None
        try:
            key = credential_manager.get_credential(key_name, timeout=2.0) if credential_manager else None
        except Exception:
            key = None
        if not key:
            checks.append(_check("key", "API key stored", FAIL,
                                 "No %s API key is stored in Windows Credential Manager.%s" % (
                                     backend, " Create one at %s." % KEY_PAGES[backend] if backend in KEY_PAGES else ""),
                                 {"action": "open_setup", "label": "Enter the API key"}))
            stop = True
        else:
            prefixes = KEY_PREFIXES.get(backend.lower())
            if prefixes and not key.startswith(prefixes):
                checks.append(_check("key", "API key stored", WARN,
                                     "A key is stored, but %s keys start with %s and this one does not: "
                                     "it may belong to another provider or be incomplete. It is tried anyway."
                                     % (backend, " or ".join("'%s'" % p for p in prefixes))))
            elif "..." in key or "…" in key:
                checks.append(_check("key", "API key stored", FAIL,
                                     "The stored key contains '...': it is the shortened form a console "
                                     "shows, not the key. Create a new key and paste all of it.",
                                     {"action": "open_setup", "label": "Enter the full key"}))
                stop = True
            else:
                checks.append(_check("key", "API key stored", OK,
                                     "Stored in Windows Credential Manager (%d characters)." % len(key)))
            key = None
    elif not stop and kind == "local_cli":
        try:
            from eye.backends.local_cli.cli_profiles import get_profile
            prof = get_profile(backend) or {}
        except Exception:
            prof = {}
        # The wizard, schema and router all store `executable_path`; `cli_path` was read
        # here alone, so a configured path was never checked.
        exe = (cfg.get("executable_path") or cfg.get("cli_path")
               or prof.get("default_executable") or "").strip().strip('"')
        found = shutil.which(exe) if exe and not os.path.isfile(exe) else (exe if exe else None)
        if not found:
            checks.append(_check("cli", "Command-line tool installed", FAIL,
                                 "'%s' was not found on this machine. To use %s: %s." % (
                                     exe or backend, prof.get("display_name") or backend,
                                     CLI_INSTALL.get(backend, "install it and put it on PATH")),
                                 {"action": "open_setup", "label": "Choose another provider"}))
            stop = True
        else:
            checks.append(_check("cli", "Command-line tool installed", OK, found))
        aliases = CLI_MODEL_ALIASES.get(backend)
        if not stop and aliases and model not in aliases and not model.startswith("claude-"):
            near = _closest(model, aliases)
            checks.append(_check("model_name", "Model name valid", FAIL,
                                 "'%s' is not a model %s accepts%s." % (
                                     model, prof.get("display_name") or backend,
                                     " - did you mean '%s'?" % near if near else
                                     " (use one of: %s)" % ", ".join(aliases[:4])),
                                 {"action": "set_model", "label": "Use '%s'" % (near or aliases[1]),
                                  "value": near or aliases[1]}))
            stop = True
    elif not stop and kind in ("local_server", "local_api"):
        base, path = SERVER_PROBES.get(backend, ("", "/models"))
        endpoint = (cfg.get("api_endpoint") or base).rstrip("/")
        if not endpoint:
            checks.append(_check("server", "Local server running", FAIL, "No server address is set.",
                                 {"action": "open_setup", "label": "Set the address"}))
            stop = True
        elif connect:
            try:
                code = _http_get(endpoint + path)
                checks.append(_check("server", "Local server running", OK if code < 400 else WARN,
                                     "%s answered (HTTP %d)." % (endpoint, code)))
            except Exception as e:
                checks.append(_check("server", "Local server running", FAIL,
                                     "Nothing answered at %s (%s). Start %s, load a model, and retry." % (
                                         endpoint, type(e).__name__, backend.replace("_", " ").title()),
                                     {"action": "retry", "label": "Retry"}))
                stop = True

    # 4. the backend answers, with the model as named
    be = getattr(router, "backend", None)
    if not stop and connect:
        if be is None:
            checks.append(_check("connect", "Connects", FAIL, "The backend could not be created from the settings.",
                                 {"action": "open_setup", "label": "Open setup"}))
            stop = True
        else:
            t = time.perf_counter()
            try:
                ok = bool(be.validate_connectivity())
                err = getattr(be, "last_error", "") or ""
            except Exception as e:
                ok, err = False, "%s: %s" % (type(e).__name__, e)
            took = time.perf_counter() - t
            if ok:
                checks.append(_check("connect", "Connects", OK, "Answered in %.1f s." % took))
            else:
                checks.append(connect_failure(router, err, took))
                stop = True

    # 4b. a real (tiny) answer: billing, quota and model-access problems show only here
    if not stop and connect and answer and be is not None:
        t = time.perf_counter()
        try:
            out = be.generate("Reply with the single word OK.", "ping",
                              gen_params={"max_output_tokens": 256})
            took = time.perf_counter() - t
            text = (out or {}).get("content", "") if isinstance(out, dict) else str(out or "")
            if (out or {}).get("refusal") if isinstance(out, dict) else False:
                checks.append(_check("answer", "Answers a question", WARN, text))
            else:
                checks.append(_check("answer", "Answers a question", OK,
                                     "Answered in %.1f s%s." % (took, ": %s" % text.strip()[:40] if text.strip() else "")))
        except Exception as e:
            took = time.perf_counter() - t
            try:
                from eye.backends.base import describe_backend_error
                err = describe_backend_error(e)
            except Exception:
                err = "%s: %s" % (type(e).__name__, e)
            c = connect_failure(router, err, took)
            c["id"], c["title"] = "answer", "Answers a question"
            checks.append(c)
            stop = True

    # 5. tools: the Eye investigates by calling them
    if not stop:
        try:
            probe = router._capability_probe() if hasattr(router, "_capability_probe") else None
            verdict = probe.resolve() if probe is not None else None
        except Exception:
            verdict = None
        if verdict:
            from eye.services import tool_capability as tc
            sup = verdict.get("support")
            st = OK if sup == "native" else (WARN if sup in ("text_protocol", "unknown") else FAIL)
            checks.append(_check("tools", "Can call the Eye's tools", st, tc.describe(verdict),
                                 None if st == OK else {"action": "open_setup",
                                                        "label": "Pick a model that calls tools"}))

    # 6. effort, where the model takes it
    if not stop:
        takes, default = False, ""
        if backend == "anthropic":
            try:
                from eye.backends.cloud_api.anthropic_backend import effort_supported
                takes = effort_supported(model)
            except Exception:
                takes = False
            default = " (high on Sonnet 5.5, medium on Haiku 5.5 and Opus 5.5)"
        elif backend == "openai":
            takes = getattr(getattr(router, "backend", None), "_is_reasoning_model", lambda: False)()
            default = " (OpenAI's own default)"
        elif backend in ("claude_code", "codex_cli"):
            # Claude Code passes --effort on; its aliases name Claude 5 models, which take it.
            takes = True
            default = " (Claude Code's own default)"
        eff = cfg.get("effort")
        if takes and not eff:
            checks.append(_check("effort", "Effort level", WARN,
                                 "Not set, so the model's default applies%s. Medium suits the Eye's "
                                 "multi-step investigations at lower cost and wait." % default,
                                 {"action": "set_effort", "label": "Use medium", "value": "medium"}))
        elif takes:
            checks.append(_check("effort", "Effort level", OK, eff))
        elif eff:
            checks.append(_check("effort", "Effort level", SKIP,
                                 "%s does not take an effort level; '%s' is ignored." % (model, eff)))

    fails = [c for c in checks if c["status"] == FAIL]
    warns = [c for c in checks if c["status"] == WARN]
    if fails:
        summary = fails[0]["detail"]
    elif warns:
        summary = "Working, with %d thing%s to look at." % (len(warns), "" if len(warns) == 1 else "s")
    else:
        summary = "Everything checks out."
    return {"ok": not fails, "summary": summary, "backend": backend, "model": model,
            "checks": checks, "seconds": round(time.perf_counter() - t0, 1),
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def connect_failure(router, err: str, took: float) -> Dict[str, Any]:
    """The 'Connects' check for a failed connection: the backend's reason, and the fix
    it points to - the closest real model name for a model that does not exist, a new
    key for a refused one, otherwise Retry."""
    cfg = getattr(router, "config", None) or {}
    backend, model = cfg.get("backend") or "", cfg.get("model_name") or ""
    be = getattr(router, "backend", None)
    err = err or ""
    fix = {"action": "retry", "label": "Retry"}
    low = err.lower()
    if "not found" in low or "404" in low or "does not exist" in low:
        names = []
        try:
            names = list(be.list_models() or []) if be is not None else []
        except Exception:
            names = []
        try:
            from eye.services.context_window_registry import curated_models
            names += [m for m in (curated_models(backend) or []) if m not in names]
        except Exception:
            pass
        near = _closest(model, names)
        if near and near != model:
            fix = {"action": "set_model", "label": "Use '%s'" % near, "value": near}
            err += "  Closest model this provider has: %s." % near
    elif "run out of credit" in low:
        page = {"anthropic": "https://console.anthropic.com/settings/billing",
                "openai": "https://platform.openai.com/settings/organization/billing",
                "openrouter": "https://openrouter.ai/settings/credits"}.get(backend)
        if page:
            err += "  Billing: %s" % page
        fix = {"action": "open_setup", "label": "Switch to another model"}
    elif "refused" in low or "401" in low or "authentication" in low or "permission" in low:
        fix = {"action": "open_setup", "label": "Enter a new key"}
    return _check("connect", "Connects", FAIL,
                  (err or "The backend did not answer.") + " (after %.1f s)" % took, fix)


def apply_fix(router, fix: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
    """Apply one of the safe fixes to the live router and, when ``persist``, to the saved
    configuration. Returns {"applied": bool, "detail": str}."""
    action = (fix or {}).get("action")
    value = (fix or {}).get("value")
    if action == "set_model" and value:
        router.switch_model(str(value))
        key, val = "model_name", str(value)
    elif action == "set_effort" and value:
        router.config["effort"] = str(value)
        if hasattr(router.backend, "effort"):
            router.backend.effort = str(value)
        key, val = "effort", str(value)
    else:
        return {"applied": False, "detail": "This fix is done in the setup window."}
    if persist:
        try:
            from eye.services.config_manager import ConfigManager
            mgr = ConfigManager()
            conf = mgr.load_config() or {}
            conf[key] = val
            mgr.save_config(conf)
        except Exception as e:
            return {"applied": True, "detail": "Applied for this session; not saved (%s)." % e}
    return {"applied": True, "detail": "%s set to %s." % (key.replace("_", " "), val)}


def record(case_directory: Optional[str], report: Dict[str, Any]) -> None:
    """Append the report to the case's EYE_Logs, so a setup problem is on record."""
    if not case_directory:
        return
    try:
        d = os.path.join(case_directory, "EYE_Logs")       # beside eye_payload_seal.jsonl
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "eye_backend_doctor.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(report, default=str) + "\n")
    except Exception as e:
        logger.warning("Backend doctor report not recorded: %s", e)


# ---- in the chat ---------------------------------------------------------------------------
# The investigator can ask in the chat as well: these work even when the model is down,
# because ContextManager answers them before its pre-flight check.
DOCTOR_QUERIES = ("check model setup", "check the model setup", "diagnose model", "/doctor")
_LABEL = {OK: "OK", WARN: "Check", FAIL: "Problem", SKIP: "Skipped"}


def is_doctor_query(query: str) -> bool:
    q = (query or "").strip().lower().rstrip("?.!")
    return q in DOCTOR_QUERIES or q.startswith("use model ") or q.startswith("use effort ")


def fix_chips(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Chat chips for the report's fixes; each chip's query is a doctor command."""
    chips = []
    for c in report.get("checks") or []:
        fix = c.get("fix") or {}
        if c.get("status") == OK or not fix:
            continue
        if fix.get("action") == "set_model" and fix.get("value"):
            chips.append({"id": "doctor_model", "label": fix["label"], "icon": "switch",
                          "query": "Use model %s" % fix["value"]})
        elif fix.get("action") == "set_effort" and fix.get("value"):
            chips.append({"id": "doctor_effort", "label": fix["label"], "icon": "switch",
                          "query": "Use effort %s" % fix["value"]})
    chips.append({"id": "doctor_again", "label": "Check the model setup", "icon": "refresh",
                  "query": "Check model setup"})
    return chips


def to_markdown(report: Dict[str, Any], heading: str = "Model setup check") -> str:
    lines = ["### %s" % heading, "",
             "**%s** - %s" % (report.get("backend") or "no provider", report.get("model") or "no model"), ""]
    for c in report.get("checks") or []:
        lines.append("- **%s** - %s: %s" % (_LABEL.get(c.get("status"), c.get("status")),
                                             c.get("title"), c.get("detail")))
    summary = report.get("summary") or ""
    if summary and not any(summary == c.get("detail") for c in report.get("checks") or []):
        lines += ["", summary]
    if not report.get("ok"):
        lines += ["", "Use a fix below, or open **Settings -> Eye AI -> Change backend** to set it up again."]
    return "\n".join(lines)


def chat_command(router, credential_manager, query: str, case_directory=None) -> Dict[str, Any]:
    """Answer a doctor command in the chat: run the checks, or apply a fix and check again."""
    q = (query or "").strip()
    low = q.lower()
    applied = ""
    if low.startswith("use model "):
        res = apply_fix(router, {"action": "set_model", "value": q[10:].strip()})
        applied = res.get("detail", "")
    elif low.startswith("use effort "):
        val = q[11:].strip().lower()
        try:
            from eye.backends.cloud_api.anthropic_backend import EFFORT_LEVELS
        except Exception:
            EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
        if val not in EFFORT_LEVELS:
            return {"response": "Effort is one of: %s." % ", ".join(EFFORT_LEVELS), "error": None,
                    "action_chips": []}
        res = apply_fix(router, {"action": "set_effort", "value": val})
        applied = res.get("detail", "")
    rep = diagnose(router, credential_manager, answer=True)
    record(case_directory, rep)
    text = to_markdown(rep)
    if applied:
        text = "%s\n\n%s" % (applied[:1].upper() + applied[1:], text)
    return {"response": text, "error": None, "action_chips": fix_chips(rep)}
