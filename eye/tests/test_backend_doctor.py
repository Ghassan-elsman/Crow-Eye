"""The backend doctor: each setup problem is found, said in words, and given its fix.

Found on the build machine on 2026-11-01: the Eye's saved model for Claude Code was
"opuse", and every question failed with a generic "backend unreachable" after the CLI
probes timed out. The doctor names the typo and offers "Use 'opus'" before any probe.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from eye.services import backend_doctor as bd  # noqa: E402


class _CM:
    def __init__(self, keys=None):
        self.keys = keys or {}

    def get_credential(self, name, timeout=2.0):
        return self.keys.get(name)


class _Backend:
    def __init__(self, ok=True, err="", models=()):
        self.ok, self.last_error, self.models, self.effort = ok, err, list(models), None

    def validate_connectivity(self):
        return self.ok

    def list_models(self):
        return self.models


class _Router:
    def __init__(self, cfg, backend=None):
        self.config = dict(cfg)
        self.backend = backend or _Backend()
        self.switched = []

    def switch_model(self, name, backend=None):
        self.switched.append(name)
        self.config["model_name"] = name


def _by_id(rep):
    return {c["id"]: c for c in rep["checks"]}


def test_nothing_set_up_says_so_and_offers_setup():
    rep = bd.diagnose(_Router({}), _CM())
    assert not rep["ok"]
    assert _by_id(rep)["backend"]["fix"]["action"] == "open_setup"


def test_cli_model_typo_is_named_with_the_fix(monkeypatch):
    monkeypatch.setattr(bd.shutil, "which", lambda exe: "C:\\bin\\%s.exe" % exe)
    rep = bd.diagnose(_Router({"backend": "claude_code", "model_name": "opuse",
                               "integration_type": "local_cli"}), _CM(), connect=False)
    c = _by_id(rep)["model_name"]
    assert c["status"] == "fail" and "did you mean 'opus'?" in c["detail"]
    assert c["fix"] == {"action": "set_model", "label": "Use 'opus'", "value": "opus"}
    assert "?." not in c["detail"]


def test_cli_not_installed_says_how_to_get_it(monkeypatch):
    monkeypatch.setattr(bd.shutil, "which", lambda exe: None)
    rep = bd.diagnose(_Router({"backend": "claude_code", "model_name": "sonnet",
                               "integration_type": "local_cli"}), _CM(), connect=False)
    c = _by_id(rep)["cli"]
    assert c["status"] == "fail" and "npm install -g @anthropic-ai/claude-code" in c["detail"]


def test_missing_key_points_to_where_keys_are_made():
    rep = bd.diagnose(_Router({"backend": "anthropic", "model_name": "claude-haiku-5-5",
                               "integration_type": "cloud_api"}), _CM(), connect=False)
    c = _by_id(rep)["key"]
    assert c["status"] == "fail" and "console.anthropic.com" in c["detail"]


def test_a_shortened_key_is_caught_before_any_request():
    rep = bd.diagnose(_Router({"backend": "anthropic", "model_name": "claude-haiku-5-5",
                               "integration_type": "cloud_api"}),
                      _CM({"anthropic_api_key": "sk-ant-api03-SGz...mgAA"}), connect=False)
    c = _by_id(rep)["key"]
    assert c["status"] == "fail" and "shortened" in c["detail"]


def test_another_providers_key_is_a_warning_and_never_shown():
    secret = "sk-proj-abcdefghijklmnop"
    rep = bd.diagnose(_Router({"backend": "anthropic", "model_name": "claude-haiku-5-5",
                               "integration_type": "cloud_api"}),
                      _CM({"anthropic_api_key": secret}), connect=False)
    assert _by_id(rep)["key"]["status"] == "warn"
    assert secret not in json.dumps(rep)


def test_a_model_that_does_not_exist_gets_the_closest_real_one():
    be = _Backend(ok=False, err="The model was not found - pick another model or check its name.",
                  models=["claude-sonnet-5-5", "claude-haiku-5-5"])
    rep = bd.diagnose(_Router({"backend": "anthropic", "model_name": "claude-sonet-5-5",
                               "integration_type": "cloud_api"}, be),
                      _CM({"anthropic_api_key": "sk-ant-x" * 10}))
    c = _by_id(rep)["connect"]
    assert c["status"] == "fail" and c["fix"]["value"] == "claude-sonnet-5-5"


def test_a_refused_key_offers_a_new_key():
    be = _Backend(ok=False, err="The API key was refused - check it in Settings -> Eye AI.")
    rep = bd.diagnose(_Router({"backend": "anthropic", "model_name": "claude-haiku-5-5",
                               "integration_type": "cloud_api"}, be),
                      _CM({"anthropic_api_key": "sk-ant-x" * 10}))
    assert _by_id(rep)["connect"]["fix"]["action"] == "open_setup"


def test_effort_unset_on_sonnet_5_5_suggests_medium():
    rep = bd.diagnose(_Router({"backend": "anthropic", "model_name": "claude-sonnet-5-5",
                               "integration_type": "cloud_api"}),
                      _CM({"anthropic_api_key": "sk-ant-x" * 10}))
    c = _by_id(rep)["effort"]
    assert c["status"] == "warn" and c["fix"] == {"action": "set_effort", "label": "Use medium",
                                                   "value": "medium"}
    assert rep["ok"]


def test_a_local_server_that_is_not_running(monkeypatch):
    def refuse(url, timeout=3.0):
        raise ConnectionRefusedError("refused")
    monkeypatch.setattr(bd, "_http_get", refuse)
    rep = bd.diagnose(_Router({"backend": "ollama", "model_name": "llama3",
                               "integration_type": "local_server"}), _CM())
    c = _by_id(rep)["server"]
    assert c["status"] == "fail" and "localhost:11434" in c["detail"]


def test_apply_fix_switches_the_model_without_saving():
    r = _Router({"backend": "claude_code", "model_name": "opuse"})
    res = bd.apply_fix(r, {"action": "set_model", "value": "opus"}, persist=False)
    assert res["applied"] and r.switched == ["opus"]
    res = bd.apply_fix(r, {"action": "set_effort", "value": "medium"}, persist=False)
    assert res["applied"] and r.config["effort"] == "medium" and r.backend.effort == "medium"
    assert not bd.apply_fix(r, {"action": "open_setup"}, persist=False)["applied"]


def test_effort_and_refusal_in_the_anthropic_backend():
    from eye.backends.cloud_api import anthropic_backend as ab
    assert ab.effort_supported("claude-sonnet-5-5") and ab.effort_supported("claude-haiku-5-5")
    assert not ab.effort_supported("claude-3-5-haiku")
    b = ab.AnthropicBackend("claude-sonnet-5-5", _CM(), effort="medium")
    assert b.effort == "medium"
    assert ab.AnthropicBackend("claude-sonnet-5-5", _CM(), effort="loud").effort is None


def test_an_empty_credit_balance_is_named_as_billing():
    from eye.backends.base import describe_backend_error
    exc = type("BadRequestError", (Exception,), {"status_code": 400})(
        "Error code: 400 - Your credit balance is too low to access the Anthropic API.")
    text = describe_backend_error(exc)
    assert "run out of credit" in text and "BadRequestError" in text
    be = _Backend(ok=False, err=text)
    rep = bd.diagnose(_Router({"backend": "anthropic", "model_name": "claude-sonnet-5-5",
                               "integration_type": "cloud_api"}, be),
                      _CM({"anthropic_api_key": "sk-ant-x" * 10}))
    c = _by_id(rep)["connect"]
    assert "console.anthropic.com/settings/billing" in c["detail"]
