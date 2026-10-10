"""The Eye's setup wizard: prefilled, checked, and a key stored only when it works.

The old wizard wrote the API key to the credential store BEFORE testing it
(and again on "Detect"), so a mistyped key stayed behind as the saved one; it
reopened on an empty form with the first provider ticked; and it accepted an
empty model or endpoint and only then failed.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt5.QtWebEngineWidgets  # noqa: F401  - must precede the QApplication
except ImportError:
    pass
from PyQt5.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from eye.ui import onboarding_wizard as W  # noqa: E402


class CM:
    def __init__(self, cfg=None):
        self.cfg, self.saved = dict(cfg or {}), None

    def load_config(self):
        return dict(self.cfg)

    def save_config(self, c):
        self.saved = dict(c)


class Cred:
    def __init__(self, stored=None):
        self.stored = dict(stored or {})
        self.writes = []

    def has_cached_credential(self, k):
        return k in self.stored

    def get_credential(self, k, timeout=2.0):
        return self.stored.get(k)

    def store_credential(self, k, v):
        self.writes.append(k)
        self.stored[k] = v


def test_missing_fields_are_named():
    assert W.missing_fields({}) == ["connection type"]
    assert W.missing_fields({"integration_type": "cloud_api", "backend": "openrouter"}) == \
        ["API key", "model"]
    assert W.missing_fields({"integration_type": "cloud_api", "backend": "openrouter",
                             "model_name": "m"}, key_stored=True) == []
    assert W.missing_fields({"integration_type": "local_api", "backend": "lm_studio"}) == \
        ["API endpoint", "model"]
    assert W.missing_fields({"integration_type": "local_cli", "backend": "ollama_cli"}) == []


def test_key_format_is_advice():
    assert W.key_format_warning("openrouter", "sk-or-v1-abc") == ""
    assert "sk-or-" in W.key_format_warning("openrouter", "sk-proj-abc")
    assert W.key_format_warning("mistral", "anything") == ""


def test_failures_are_explained():
    assert "refused the API key" in W.explain_failure("Error code: 401", "cloud_api")
    assert "server running" in W.explain_failure("Connection refused", "local_api")


def test_overlay_never_writes_the_key_through():
    base = Cred()
    o = W._OverlayCredentials(base, {"openrouter_api_key": "sk-or-new"})
    assert o.get_credential("openrouter_api_key") == "sk-or-new"
    o.store_credential("x_api_key", "v")
    assert base.writes == []


def test_a_saved_setup_reopens_prefilled_on_the_backend_step():
    w = W.OnboardingWizard(CM({"integration_type": "local_api", "backend": "lm_studio",
                               "api_endpoint": "http://localhost:1234", "model_name": "qwen"}),
                           Cred(), None, start_step="backend")
    assert w.pages.currentIndex() == 2
    assert w._fields["backend"].currentData() == "lm_studio"
    assert w._fields["api_endpoint"].text() == "http://localhost:1234"
    assert w._fields["model_name"].text() == "qwen"


def test_next_is_refused_while_a_field_is_missing():
    w = W.OnboardingWizard(CM({"integration_type": "cloud_api", "backend": "openrouter"}),
                           Cred(), None, start_step="backend")
    w._on_next()
    assert w.pages.currentIndex() == 2 and "API key" in w.form_message.text()


def test_a_failed_test_stores_nothing_and_cannot_be_saved():
    cred = Cred()
    cm = CM({"integration_type": "cloud_api", "backend": "openrouter", "model_name": "m"})
    w = W.OnboardingWizard(cm, cred, None, start_step="backend")
    w._fields["api_key"].setText("sk-or-typo")
    w._on_next()
    w._test_fp = w._fingerprint()
    w._on_validation_done(False, "401 Unauthorized", 100)
    assert cred.writes == [] and cm.saved is None
    assert not w.next_button.isEnabled()


def test_a_passed_test_saves_and_stores_the_key_once():
    cred = Cred()
    cm = CM({"integration_type": "cloud_api", "backend": "openrouter", "model_name": "m"})
    w = W.OnboardingWizard(cm, cred, None, start_step="backend")
    w._fields["api_key"].setText("sk-or-good")
    w._on_next()
    w._test_fp = w._fingerprint()
    w._on_validation_done(True, "", 500)
    assert w.next_button.isEnabled()
    w._on_next()
    assert cred.writes == ["openrouter_api_key"]
    assert cm.saved["backend"] == "openrouter" and "api_key" not in cm.saved


def test_changing_a_setting_after_the_test_requires_a_new_test():
    w = W.OnboardingWizard(CM({"integration_type": "local_api", "backend": "lm_studio",
                               "api_endpoint": "http://x:1", "model_name": "a"}),
                           Cred(), None, start_step="backend")
    w._on_next()
    w._test_fp = w._fingerprint()
    w._on_validation_done(True, "", 10)
    w._fields["model_name"].setText("b")
    w._collect_fields()
    w._go(3)
    assert not w.next_button.isEnabled()
