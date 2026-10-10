"""
Eye AI setup - connecting the Eye to a language model.

Opens the first time the Eye is started (and from Settings -> Eye AI ->
Change backend). Four steps, shown in a step bar at the top:

1. Welcome     - what the Eye does with the model.
2. Connection  - local command-line agent, local API server, or cloud API.
3. Backend     - the provider, its address / executable / key, and the model.
4. Test & save - a live connection test, then save.

What it guarantees:

* **An API key is written to the credential store only after it worked.**
  The test (and model detection) run through an in-memory overlay of the
  store, so a mistyped key is never left behind as the saved one.
* **It opens on what is configured.** Connection type, provider, endpoint,
  executable and model are pre-filled; a stored key is said ("a key is
  stored - leave blank to keep it"), never shown.
* **Problems are said in the window, not in a stack of message boxes.**
  Missing fields and an unusual key format are named under the form; the
  test result (with the reason when it fails) is shown on the last step.
* **Nothing slow runs on the GUI thread** - the connection test and the
  diagnostics each run on a worker thread.
"""

import time

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QLineEdit, QMessageBox, QWidget, QStackedWidget, QFormLayout, QComboBox,
    QFrame, QFileDialog, QButtonGroup, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QPalette, QColor

from styles import CrowEyeStyles, Colors


# ----------------------------------------------------------------------------
# Plain helpers (no Qt) - unit-tested
# ----------------------------------------------------------------------------

PROVIDER_LABELS = {
    "openrouter": "OpenRouter",
    "gemini": "Gemini (Google AI Studio)",
    "nvidia": "NVIDIA",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "kimi": "Kimi (Moonshot)",
    "groq": "Groq",
    "mistral": "Mistral",
    "xai": "xAI (Grok)",
    # local command-line agents
    "gemini_cli": "Gemini CLI", "llama": "LLaMA (llama.cpp)", "claude_code": "Claude Code",
    "jules_cli": "Jules CLI", "gpt_cli": "GPT CLI", "ollama_cli": "Ollama",
    "custom_cli": "Custom command-line agent",
    # local API servers
    "ollama": "Ollama server", "lm_studio": "LM Studio", "vllm": "vLLM",
}

# What a key from each provider starts with, and where to get one.
KEY_PREFIXES = {
    "openai": ("sk-",), "gemini": ("AIza",), "anthropic": ("sk-ant-",),
    "deepseek": ("sk-",), "kimi": ("sk-",), "openrouter": ("sk-or-",),
    "nvidia": ("nvapi-",), "groq": ("gsk_",), "xai": ("xai-",),
}
KEY_SOURCES = {
    "openrouter": "openrouter.ai/keys", "nvidia": "build.nvidia.com",
    "groq": "console.groq.com", "gemini": "aistudio.google.com/apikey",
    "openai": "platform.openai.com/api-keys", "anthropic": "console.anthropic.com",
    "deepseek": "platform.deepseek.com", "kimi": "platform.moonshot.ai",
    "mistral": "console.mistral.ai", "xai": "console.x.ai",
}

CLOUD_ORDER = ("openrouter", "gemini", "nvidia", "openai", "anthropic",
               "deepseek", "kimi", "groq", "mistral", "xai")

INTEGRATIONS = (
    ("local_cli", "Local command-line agent",
     "A model run on this machine through a command-line tool. Nothing leaves "
     "the machine - suitable for air-gapped work.",
     "Ollama, local LLaMA, Gemini CLI"),
    ("local_api", "Local API server",
     "A model served over HTTP on this machine or your local network.",
     "LM Studio, vLLM, Ollama server"),
    ("cloud_api", "Cloud API",
     "A hosted model reached over the internet with an API key.",
     "OpenRouter, Google Gemini, NVIDIA, OpenAI, Anthropic, DeepSeek, Kimi, Groq, Mistral, xAI"),
)

STEPS = (("welcome", "Welcome"), ("connection", "Connection"),
         ("backend", "Backend & model"), ("test", "Test & save"))


def provider_label(backend):
    return PROVIDER_LABELS.get(backend, (backend or "").replace("_", " ").title())


def key_format_warning(backend, key):
    """'' when the key looks like the provider's, else a sentence saying what
    it usually starts with. Advice only: prefixes change, the test decides."""
    prefixes = KEY_PREFIXES.get(backend)
    if not key or not prefixes or key.startswith(prefixes):
        return ""
    where = KEY_SOURCES.get(backend)
    return ("%s keys usually start with '%s' - check it was copied whole%s."
            % (provider_label(backend), prefixes[0],
               (" (get one at %s)" % where) if where else ""))


def missing_fields(config, key_stored=False):
    """Names of the fields that must be filled before a test can mean anything."""
    kind = config.get("integration_type")
    missing = []
    if not kind:
        return ["connection type"]
    if not config.get("backend"):
        missing.append("backend")
    if kind == "local_api":
        if not (config.get("api_endpoint") or "").strip():
            missing.append("API endpoint")
        if not (config.get("model_name") or "").strip():
            missing.append("model")
    elif kind == "cloud_api":
        if not (config.get("api_key") or "").strip() and not key_stored:
            missing.append("API key")
        if not (config.get("model_name") or "").strip():
            missing.append("model")
    return missing


def explain_failure(detail, kind):
    """A failed test, in words an examiner can act on."""
    d = (detail or "").lower()
    if any(s in d for s in ("401", "unauthor", "invalid api key", "incorrect api key",
                            "permission", "403", "forbidden")):
        return "The provider refused the API key. Check it is complete and active."
    if any(s in d for s in ("404", "not found", "does not exist", "model_not_found")):
        return "The provider does not offer that model name. Use Detect or Common Models."
    if any(s in d for s in ("timed out", "timeout")):
        return "No answer in time. The server may be busy, or unreachable from here."
    if any(s in d for s in ("connection", "refused", "resolve", "dns", "unreachable",
                            "getaddrinfo", "max retries")):
        if kind == "local_api":
            return "Nothing answered at that address. Is the server running, with a model loaded?"
        return "Could not reach the provider. Check the internet connection or proxy."
    if any(s in d for s in ("not found in path", "no such file", "cannot find", "winerror 2")):
        return "The executable was not found. Browse to it, or check it is on PATH."
    if detail:
        return detail.splitlines()[0][:300]
    if kind == "local_cli":
        return "The agent did not respond. Check the executable path and that a model is installed."
    if kind == "local_api":
        return "The server did not respond. Check the endpoint and that a model is loaded."
    return "The provider did not respond. Check the key, the model and the connection."


class _OverlayCredentials:
    """The credential store as the router sees it, with the key being tried
    held in memory only. A key that fails its test is never written - the old
    wizard stored it before testing, so a typo stayed behind as the saved key."""

    def __init__(self, base, overrides=None):
        self._base = base
        self._over = dict(overrides or {})

    def get_credential(self, key, timeout=2.0):
        if key in self._over:
            return self._over[key]
        return self._base.get_credential(key, timeout) if self._base else None

    def has_cached_credential(self, key):
        return key in self._over or bool(self._base and self._base.has_cached_credential(key))

    def store_credential(self, key, value):
        self._over[key] = value

    def delete_credential(self, key):
        self._over.pop(key, None)

    def __getattr__(self, name):
        return getattr(self._base, name)


def stored_key_exists(credential_manager, backend):
    """Is a key for `backend` already in the credential store? Quick: the
    in-memory cache first, then a short keychain lookup."""
    if not credential_manager or not backend:
        return False
    name = "%s_api_key" % backend
    try:
        if credential_manager.has_cached_credential(name):
            return True
        return bool(credential_manager.get_credential(name, timeout=0.6))
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Workers
# ----------------------------------------------------------------------------

class _WizardConnectivityWorker(QThread):
    """The connection test, off the GUI thread. Emits done(ok, detail, ms).

    Runs on the wizard's live ``config`` dict, so a local CLI agent's
    auto-selected model (ModelRouter.validate_connectivity) carries into the
    save. The key under test reaches the router through an overlay - nothing
    is stored here."""
    done = pyqtSignal(bool, str, int)

    def __init__(self, config, credential_manager, api_key=None):
        super().__init__()
        self._config = config
        self._credential_manager = credential_manager
        self._api_key = api_key

    def run(self):
        started = time.monotonic()
        try:
            overrides = {}
            if self._api_key:
                overrides["%s_api_key" % self._config.get("backend")] = self._api_key
            creds = _OverlayCredentials(self._credential_manager, overrides)
            from eye.services.model_router import ModelRouter
            router = ModelRouter(self._config, creds)
            ok = bool(router.validate_connectivity())
            self.done.emit(ok, "", int((time.monotonic() - started) * 1000))
        except Exception as e:
            self.done.emit(False, str(e), int((time.monotonic() - started) * 1000))


class _DiagnosticsWorker(QThread):
    """System diagnostics off the GUI thread (they import every SDK)."""
    done = pyqtSignal(object, str)

    def __init__(self, config_manager, credential_manager):
        super().__init__()
        self._cm, self._cred = config_manager, credential_manager

    def run(self):
        try:
            from eye.services.diagnostics import SystemDiagnostics
            self.done.emit(SystemDiagnostics(self._cm, self._cred).run_full_check(), "")
        except Exception as e:
            self.done.emit(None, str(e))


# ----------------------------------------------------------------------------
# Styling
# ----------------------------------------------------------------------------

# The site's tokens (ui/site_theme.py). The wizard keeps its own rules below
# (page titles, cards, the selected option card, the link button) as the
# window sheet's extra; everything else - inputs, combos, lists, check boxes,
# scroll bars - comes from the site sheet, buttons from its role family.
try:
    from ui import site_theme as _site
except Exception:                                   # pragma: no cover
    _site = None
_BG = "#0A0C10"
try:
    from pathlib import Path as _Path
    import correlation_engine.gui.crow_eye_icons as _icons
    _DOWN_ICON = (_Path(_icons.__file__).parent / "icons" / "down.svg").as_posix()
except Exception:
    _DOWN_ICON = ""
_CARD = "#0F172A"
_BORDER = "rgba(255, 255, 255, 0.14)"
_ACCENT = "#A5B4FC"
_TEXT = "#E2E8F0"
_MUTED = "#94A3B8"
_WARN, _OK, _BAD = "#FBBF24", "#4ADE80", "#FDA4AF"

_WIZARD_STYLE = f"""
QWidget#wizardBody {{ background-color: {_BG}; }}
QLabel#pageTitle {{ color: #F8FAFC; font-size: 20px; font-weight: 800; }}
QLabel#pageIntro {{ color: {_MUTED}; font-size: 13px; }}
QLabel#fieldLabel {{ color: {_TEXT}; font-size: 13px; font-weight: 600; }}
QLabel#hint {{ color: {_MUTED}; font-size: 12px; }}
QLabel#formMessage {{ color: {_WARN}; font-size: 12px; font-weight: 600; }}
QFrame#card, QFrame#optionCard {{ background-color: {_CARD}; border: 1px solid {_BORDER}; border-radius: 14px; }}
QFrame#optionCard[selected="true"] {{ border: 2px solid #6366F1; background-color: #111A33; }}
QFrame#optionCard:hover {{ border: 1px solid rgba(99, 102, 241, 0.55); }}
QFrame#card QLabel, QFrame#optionCard QLabel {{ background: transparent; border: none; }}
QRadioButton {{ color: {_TEXT}; font-size: 14px; font-weight: 700; spacing: 10px; background: transparent; }}
QPushButton#linkButton {{ background: transparent; color: {_MUTED}; border: none; font-size: 12px;
                          text-decoration: underline; padding: 4px; min-width: 0; }}
QPushButton#linkButton:hover {{ color: {_ACCENT}; }}
"""


def _wizard_sheet(dialog):
    """The site sheet plus the wizard's own rules, before the children exist."""
    if _site is not None:
        _site.begin_site_theme(dialog, extra=_WIZARD_STYLE)
    else:
        dialog.setStyleSheet(_WIZARD_STYLE)


def _variant(button, variant):
    """A button in the site's role family (also at run time: Next <-> Save)."""
    if _site is None:
        return
    button.setStyleSheet("")
    _site.restyle(button, variant)


class CloudAPIWarningDialog(QDialog):
    """Said once, before a cloud provider is configured: case data will be
    sent over the internet, which may need approval."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cloud API - before you continue")
        self.setMinimumWidth(520)
        _wizard_sheet(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(16)
        try:
            from correlation_engine.gui.crow_eye_icons import apply_status_to_label
            icon = QLabel()
            apply_status_to_label(icon, "warning", "", size_px=40)
            icon.setAlignment(Qt.AlignCenter)
            layout.addWidget(icon)
        except Exception:
            pass
        title = QLabel("Case data will leave this machine")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        body = QLabel(
            "With a cloud API, the questions you ask and the evidence the Eye reads to "
            "answer them are sent to the provider over the internet.\n\n"
            "Your organisation may need to approve this before it is used on a case. "
            "A local agent or a local API server keeps everything on this machine.")
        body.setWordWrap(True)
        body.setObjectName("pageIntro")
        layout.addWidget(body)
        row = QHBoxLayout()
        row.addStretch()
        back = QPushButton("Go back")
        _variant(back, "ghost")
        back.clicked.connect(self.reject)
        go = QPushButton("I understand, continue")
        _variant(go, "warning")              # a choice with a consequence
        go.clicked.connect(self.accept)
        row.addWidget(back)
        row.addWidget(go)
        layout.addLayout(row)


class OnboardingWizard(QDialog):
    """Connect the Eye to a language model (see the module docstring).

    ``start_step="backend"`` opens on the Backend step when a connection type
    is already configured - Settings -> Eye AI -> Change backend.
    """

    configuration_complete = pyqtSignal(dict)

    def __init__(self, config_manager, credential_manager, model_router, parent=None,
                 start_step=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.config_manager = config_manager
        self.credential_manager = credential_manager
        self.model_router = model_router

        self.config = {
            "integration_type": None, "backend": None, "model_name": "",
            "executable_path": "", "api_endpoint": "", "last_validated": None,
        }
        try:
            existing = self.config_manager.load_config() if self.config_manager else None
            if existing:
                self.config.update(existing)
        except Exception as e:
            print(f"[Warning] Failed to load the existing Eye configuration: {e}")
        self.config.pop("api_key", None)

        self._cloud_acknowledged = self.config.get("integration_type") == "cloud_api"
        self._built_for = None            # (integration) the backend form was built for
        self._tested = None               # fingerprint of the settings that passed a test
        self._testing = False
        self._fields = {}

        self._init_ui()
        if start_step == "backend" and self.config.get("integration_type"):
            self._go(2)
        else:
            self._go(0)

    # ---- layout ---------------------------------------------------------------
    def _init_ui(self):
        self.setWindowTitle("Eye AI - connect a language model")
        self.setMinimumSize(860, 640)
        self.resize(920, 700)
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(_BG))
        palette.setColor(QPalette.WindowText, QColor(_TEXT))
        self.setPalette(palette)
        _wizard_sheet(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(f"QFrame {{ background-color: {_CARD}; border-bottom: 1px solid {_BORDER}; }}")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(32, 18, 32, 14)
        hl.setSpacing(12)
        brand = QLabel("Eye AI setup")
        brand.setStyleSheet(f"color: {_ACCENT}; font-size: 15px; font-weight: 700; background: transparent;"
                            f" border: none;")
        hl.addWidget(brand)
        steps = QHBoxLayout()
        steps.setSpacing(8)
        self._step_labels = []
        for i, (_key, name) in enumerate(STEPS):
            lab = QLabel("%d  %s" % (i + 1, name))
            lab.setAlignment(Qt.AlignCenter)
            self._step_labels.append(lab)
            steps.addWidget(lab, 1)
        hl.addLayout(steps)
        outer.addWidget(header)

        self.pages = QStackedWidget()
        body = QWidget()
        body.setObjectName("wizardBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(36, 26, 36, 10)
        bl.addWidget(self.pages)
        outer.addWidget(body, 1)

        for builder in (self._page_welcome, self._page_connection, self._page_backend,
                        self._page_test):
            self.pages.addWidget(builder())

        footer = QFrame()
        footer.setStyleSheet(f"QFrame {{ background-color: {_CARD}; border-top: 1px solid {_BORDER}; }}")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(28, 12, 28, 14)
        fl.setSpacing(10)
        self.diag_button = QPushButton("Run diagnostics")
        self.diag_button.setObjectName("linkButton")
        self.diag_button.setCursor(Qt.PointingHandCursor)
        self.diag_button.setToolTip("Check the installed AI SDKs, the configuration and the environment")
        self.diag_button.clicked.connect(self._on_run_diagnostics)
        fl.addWidget(self.diag_button)
        fl.addStretch()
        self.cancel_button = QPushButton("Cancel")
        _variant(self.cancel_button, "ghost")
        self.cancel_button.clicked.connect(self.reject)
        self.back_button = QPushButton("Back")
        _variant(self.back_button, "ghost")
        self.back_button.clicked.connect(self._on_back)
        self.next_button = QPushButton("Next")
        _variant(self.next_button, "primary")
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self._on_next)
        for b in (self.cancel_button, self.back_button, self.next_button):
            fl.addWidget(b)
        outer.addWidget(footer)

    def _title(self, layout, text, intro=None):
        t = QLabel(text)
        t.setObjectName("pageTitle")
        layout.addWidget(t)
        if intro:
            i = QLabel(intro)
            i.setObjectName("pageIntro")
            i.setWordWrap(True)
            layout.addWidget(i)

    def _page_welcome(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(14)
        self._title(lay, "Connect the Eye to a language model",
                    "The Eye answers questions about the case by reading its parsed artifacts "
                    "and asking a language model to reason over them. Pick the model it uses "
                    "here; you can change it any time in Settings -> Eye AI.")
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        points = QLabel(
            "<div style='line-height:1.55'>"
            "<b style='color:#A5B4FC'>What the Eye does</b><br>"
            "&bull; Answers questions in plain language, with the rows it used as evidence.<br>"
            "&bull; Reads the case read-only - the evidence databases are never changed.<br>"
            "&bull; Records what was sent to the model, for the chain of custody.<br><br>"
            "<b style='color:#A5B4FC'>Three ways to connect</b><br>"
            "&bull; <b>Local command-line agent</b> - everything stays on this machine.<br>"
            "&bull; <b>Local API server</b> - LM Studio, vLLM or Ollama on this machine or the LAN.<br>"
            "&bull; <b>Cloud API</b> - a hosted model, reached with an API key.</div>")
        points.setWordWrap(True)
        points.setTextFormat(Qt.RichText)
        cl.addWidget(points)
        lay.addWidget(card)
        lay.addStretch()
        return page

    def _page_connection(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        self._title(lay, "How should the Eye reach the model?",
                    "Choose by where the model runs. Only the cloud option sends case data "
                    "off this machine.")
        self.integration_group = QButtonGroup(self)
        self._option_cards = {}
        for value, title, desc, supports in INTEGRATIONS:
            card = QFrame()
            card.setObjectName("optionCard")
            card.setCursor(Qt.PointingHandCursor)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(18, 14, 18, 14)
            cl.setSpacing(4)
            radio = QRadioButton(title)
            radio.toggled.connect(lambda on, v=value: on and self._on_integration_selected(v))
            self.integration_group.addButton(radio)
            cl.addWidget(radio)
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setObjectName("pageIntro")
            d.setContentsMargins(26, 0, 0, 0)
            cl.addWidget(d)
            s = QLabel("Works with: " + supports)
            s.setWordWrap(True)
            s.setObjectName("hint")
            s.setContentsMargins(26, 0, 0, 0)
            cl.addWidget(s)
            if value == "cloud_api":
                w = QLabel("Sends case data over the internet - organisational approval may be required.")
                w.setWordWrap(True)
                w.setStyleSheet(f"color: {_WARN}; font-size: 12px; font-weight: 600;")
                w.setContentsMargins(26, 4, 0, 0)
                cl.addWidget(w)
            card.mousePressEvent = lambda _e, r=radio: r.setChecked(True)
            self._option_cards[value] = (card, radio)
            lay.addWidget(card)
        lay.addStretch()
        current = self.config.get("integration_type")
        if current in self._option_cards:
            self._option_cards[current][1].setChecked(True)
        return page

    def _page_backend(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        self._backend_title = QLabel()
        self._backend_title.setObjectName("pageTitle")
        lay.addWidget(self._backend_title)
        self._backend_intro = QLabel()
        self._backend_intro.setObjectName("pageIntro")
        self._backend_intro.setWordWrap(True)
        lay.addWidget(self._backend_intro)
        self._form_card = QFrame()
        self._form_card.setObjectName("card")
        self._form_layout = QFormLayout(self._form_card)
        self._form_layout.setContentsMargins(20, 18, 20, 18)
        self._form_layout.setHorizontalSpacing(16)
        self._form_layout.setVerticalSpacing(12)
        self._form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._form_card)
        self.form_message = QLabel("")
        self.form_message.setObjectName("formMessage")
        self.form_message.setWordWrap(True)
        lay.addWidget(self.form_message)
        lay.addStretch()
        return page

    def _page_test(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(14)
        self._title(lay, "Test the connection, then save",
                    "The Eye sends one short request to the model. Nothing is saved until "
                    "the test passes - including the API key.")
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        self.summary_label = QLabel()
        self.summary_label.setTextFormat(Qt.RichText)
        self.summary_label.setWordWrap(True)
        cl.addWidget(self.summary_label)
        lay.addWidget(card)
        row = QHBoxLayout()
        self.test_button = QPushButton("Test connection")
        _variant(self.test_button, "primary")
        self.test_button.clicked.connect(self._begin_validation)
        row.addWidget(self.test_button)
        row.addStretch()
        lay.addLayout(row)
        self.status_label = QLabel("Not tested yet.")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.RichText)
        self.status_label.setStyleSheet(f"color: {_MUTED}; font-size: 13px;")
        lay.addWidget(self.status_label)
        lay.addStretch()
        return page

    # ---- step bar / navigation -----------------------------------------------------
    def _go(self, index):
        if index == 2:
            self._build_backend_form()
        if index == 3:
            self._refresh_summary()
        self.pages.setCurrentIndex(index)
        for i, lab in enumerate(self._step_labels):
            if i == index:
                css = "color: #FFFFFF; background: #6366F1; font-weight: 700;"
            elif i < index:
                css = f"color: {_ACCENT}; background: rgba(99, 102, 241, 0.16); font-weight: 600;"
            else:
                css = "color: #64748B; background: #131C31; font-weight: 600;"
            lab.setStyleSheet(css + " border: none; border-radius: 12px; padding: 5px 10px;"
                                    " font-size: 12px;")
        self.back_button.setEnabled(index > 0 and not self._testing)
        if index == 3:
            self.next_button.setText("Save")
            _variant(self.next_button, "primary")
            self.next_button.setEnabled(self._tested == self._fingerprint())
        else:
            self.next_button.setText("Next")
            _variant(self.next_button, "primary")
            self.next_button.setEnabled(index != 1 or bool(self.config.get("integration_type")))

    def _on_integration_selected(self, integration_type):
        self.config["integration_type"] = integration_type
        for value, (card, _radio) in getattr(self, "_option_cards", {}).items():
            card.setProperty("selected", "true" if value == integration_type else "false")
            card.style().unpolish(card)
            card.style().polish(card)
        if self.pages.currentIndex() == 1:
            self.next_button.setEnabled(True)

    def _on_next(self):
        step = self.pages.currentIndex()
        if step == 0:
            self._go(1)
        elif step == 1:
            if not self.config.get("integration_type"):
                return
            if self.config["integration_type"] == "cloud_api" and not self._cloud_acknowledged:
                if CloudAPIWarningDialog(self).exec_() != QDialog.Accepted:
                    return
                self._cloud_acknowledged = True
            self._go(2)
        elif step == 2:
            self._collect_fields()
            missing = missing_fields(self._config_with_key(), self._key_stored())
            if missing:
                self.form_message.setText("Still needed: " + ", ".join(missing) + ".")
                return
            self.form_message.setText("")
            self._go(3)
        elif step == 3:
            if self._tested == self._fingerprint():
                self._save()

    def _on_back(self):
        if self.pages.currentIndex() > 0 and not self._testing:
            if self.pages.currentIndex() == 2:
                self._collect_fields()
            self._go(self.pages.currentIndex() - 1)

    # ---- the backend form ---------------------------------------------------------
    def _backends_for(self, kind):
        from eye.backends import backend_registry as reg
        if kind == "local_cli":
            return list(reg.LOCAL_CLI_BACKENDS)
        if kind == "local_api":
            return list(reg.LOCAL_SERVER_BACKENDS)
        return [b for b in CLOUD_ORDER if b in reg.CLOUD_API_BACKENDS]

    def _build_backend_form(self):
        kind = self.config.get("integration_type")
        if self._built_for == kind:
            self._update_key_hint()
            return
        self._built_for = kind
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)
        self._fields = {}
        titles = {
            "local_cli": ("Local command-line agent",
                          "Point the Eye at the agent's executable. Leave the model empty to use "
                          "the agent's default (the first installed model is picked)."),
            "local_api": ("Local API server",
                          "The address the server listens on, and the model it has loaded."),
            "cloud_api": ("Cloud API",
                          "The provider, your API key for it, and the model to use."),
        }
        title, intro = titles.get(kind, ("Backend", ""))
        self._backend_title.setText(title)
        self._backend_intro.setText(intro)

        backends = self._backends_for(kind)
        combo = QComboBox()
        for b in backends:
            combo.addItem(provider_label(b), b)
        current = self.config.get("backend")
        idx = combo.findData(current) if current in backends else 0
        combo.setCurrentIndex(max(0, idx))
        self.config["backend"] = combo.currentData()
        combo.currentIndexChanged.connect(lambda _i: self._on_backend_selected(combo.currentData()))
        self._fields["backend"] = combo
        self._add_row("Provider" if kind == "cloud_api" else "Backend", combo)

        if kind == "local_cli":
            path = self._line("executable_path", "e.g. C:\\Program Files\\Ollama\\ollama.exe")
            browse = QPushButton("Browse...")
            _variant(browse, "ghost")
            browse.clicked.connect(self._browse_executable)
            self._add_row("Executable", self._hbox(path, browse))
            self._add_row("Model", self._model_row(detect=False),
                          "Optional - empty uses the agent's default model.")
        elif kind == "local_api":
            self._add_row("API endpoint", self._line(
                "api_endpoint", "http://localhost:1234 (LM Studio) - http://localhost:11434 (Ollama)"))
            self._add_row("Model", self._model_row(detect=True))
        else:
            key = self._line("api_key", "Paste the API key", password=True)
            show = QCheckBox("Show")
            show.toggled.connect(lambda on: key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
            self._add_row("API key", self._hbox(key, show))
            self._key_hint = QLabel()
            self._key_hint.setObjectName("hint")
            self._key_hint.setWordWrap(True)
            self._form_layout.addRow("", self._key_hint)
            key.textChanged.connect(lambda _t: self._update_key_hint())
            self._add_row("Model", self._model_row(detect=True))
            self._update_key_hint()

    def _add_row(self, label, widget, hint=None):
        lab = QLabel(label)
        lab.setObjectName("fieldLabel")
        self._form_layout.addRow(lab, widget)
        if hint:
            h = QLabel(hint)
            h.setObjectName("hint")
            self._form_layout.addRow("", h)

    @staticmethod
    def _hbox(*widgets):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        for x in widgets:
            h.addWidget(x, 1 if isinstance(x, QLineEdit) else 0)
        return w

    def _line(self, key, placeholder, password=False):
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        if password:
            edit.setEchoMode(QLineEdit.Password)
        elif self.config.get(key):
            edit.setText(str(self.config.get(key)))
        edit.textChanged.connect(lambda _t: self._invalidate_test())
        self._fields[key] = edit
        return edit

    def _model_row(self, detect):
        model = self._line("model_name", "e.g. a model id - or use Detect / Common models")
        parts = [model]
        if detect:
            d = QPushButton("Detect")
            d.setToolTip("Ask the provider or server which models it offers")
            _variant(d, "ghost")
            d.clicked.connect(self._detect_models)
            parts.append(d)
            if self.config.get("integration_type") == "cloud_api":
                c = QPushButton("Common models")
                c.setToolTip("A built-in list - no key or network needed")
                _variant(c, "ghost")
                c.clicked.connect(self._show_common_models)
                parts.append(c)
        return self._hbox(*parts)

    def _on_backend_selected(self, backend):
        self.config["backend"] = backend
        self._invalidate_test()
        self._update_key_hint()

    def _key_stored(self):
        if self.config.get("integration_type") != "cloud_api":
            return False
        return stored_key_exists(self.credential_manager, self.config.get("backend"))

    def _update_key_hint(self):
        hint = getattr(self, "_key_hint", None)
        if hint is None or self.config.get("integration_type") != "cloud_api":
            return
        backend = self.config.get("backend")
        typed = self._fields.get("api_key").text().strip() if self._fields.get("api_key") else ""
        warn = key_format_warning(backend, typed)
        if warn:
            hint.setText(warn)
            hint.setStyleSheet(f"color: {_WARN}; font-size: 12px;")
            return
        hint.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        if typed:
            hint.setText("Kept in the Windows credential store once the test passes - never in a file.")
        elif self._key_stored():
            hint.setText("A key for %s is already stored - leave this empty to keep it."
                         % provider_label(backend))
        else:
            where = KEY_SOURCES.get(backend)
            hint.setText("Get a key at %s." % where if where else "")

    def _browse_executable(self):
        path, _f = QFileDialog.getOpenFileName(self, "Choose the agent's executable", "",
                                               "Programs (*.exe *.bat *.cmd);;All files (*)")
        if path:
            self._fields["executable_path"].setText(path)

    def _collect_fields(self):
        for key, w in self._fields.items():
            if key == "backend":
                self.config["backend"] = w.currentData()
            elif key == "api_key":
                continue                    # held in the field, never in self.config
            else:
                self.config[key] = w.text().strip()

    def _typed_key(self):
        w = self._fields.get("api_key")
        return w.text().strip() if w else ""

    def _config_with_key(self):
        c = dict(self.config)
        if self._typed_key():
            c["api_key"] = self._typed_key()
        return c

    def _fingerprint(self):
        c = self._config_with_key()
        return tuple(str(c.get(k) or "") for k in
                     ("integration_type", "backend", "model_name", "executable_path",
                      "api_endpoint", "api_key"))

    def _invalidate_test(self):
        self._tested = None

    # ---- step 4: test and save ---------------------------------------------------------
    def _refresh_summary(self):
        c = self.config
        kind = dict((v, t) for v, t, _d, _s in INTEGRATIONS).get(c.get("integration_type"), "-")
        rows = [("Connection", kind), ("Backend", provider_label(c.get("backend")))]
        if c.get("integration_type") == "local_cli":
            rows.append(("Executable", c.get("executable_path") or "(on PATH)"))
        if c.get("integration_type") == "local_api":
            rows.append(("Endpoint", c.get("api_endpoint")))
        if c.get("integration_type") == "cloud_api":
            rows.append(("API key", "entered now - stored after the test passes" if self._typed_key()
                         else "the stored key"))
        rows.append(("Model", c.get("model_name") or "(the agent's default)"))
        html = "<table cellspacing='0' cellpadding='4'>" + "".join(
            "<tr><td style='color:#94A3B8; padding-right:18px'>%s</td><td><b>%s</b></td></tr>"
            % (k, _esc(v)) for k, v in rows) + "</table>"
        warn = key_format_warning(c.get("backend"), self._typed_key())
        if warn:
            html += "<p style='color:#FBBF24'>%s</p>" % _esc(warn)
        self.summary_label.setText(html)
        if self._tested != self._fingerprint():
            self._set_status("Not tested yet.", _MUTED)

    def _set_status(self, text, color, rich=False):
        self.status_label.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600;")
        self.status_label.setText(text if rich else _esc(text))

    def _begin_validation(self):
        """Run the connection test on a worker thread; the result is shown in
        the window (no modal progress box)."""
        if self._testing:
            return
        self._testing = True
        self._tested = None
        self.test_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self._dots = 0
        self._spin = QTimer(self)
        self._spin.timeout.connect(self._tick)
        self._spin.start(350)
        self._tick()
        worker = _WizardConnectivityWorker(self.config, self.credential_manager,
                                           api_key=self._typed_key() or None)
        self._validation_worker = worker
        self._test_fp = self._fingerprint()
        worker.done.connect(self._on_validation_done)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self._set_status("Testing the connection to %s%s"
                         % (provider_label(self.config.get("backend")), "." * (self._dots + 1)),
                         _ACCENT)

    def _on_validation_done(self, ok, detail, ms=0):
        if getattr(self, "_spin", None):
            self._spin.stop()
        self._testing = False
        self.test_button.setEnabled(True)
        self.back_button.setEnabled(True)
        backend = provider_label(self.config.get("backend"))
        if ok:
            # A local agent may have picked its model during the test - shown,
            # and the tested settings are what gets saved.
            w = self._fields.get("model_name")
            if w is not None and (w.text().strip() != (self.config.get("model_name") or "")):
                w.blockSignals(True)
                w.setText(self.config.get("model_name") or "")
                w.blockSignals(False)
            self._tested = self._fingerprint()
            self._refresh_summary()
            model = self.config.get("model_name") or "default model"
            self._set_status("&#10003;&nbsp; Connected to %s - %s answered in %.1f s. Click Save."
                             % (_esc(backend), _esc(model), ms / 1000.0), _OK, rich=True)
        else:
            self._tested = None
            reason = explain_failure(detail, self.config.get("integration_type"))
            self._set_status("&#10007;&nbsp; Could not connect to %s. %s<br>"
                             "<span style='color:#94A3B8; font-weight:400'>Go Back to change a "
                             "setting, then test again.</span>" % (_esc(backend), _esc(reason)),
                             _BAD, rich=True)
        self.next_button.setEnabled(self._tested == self._fingerprint())

    def _save(self):
        config = dict(self.config)
        if self._typed_key():
            config["api_key"] = self._typed_key()
        self.save_configuration(config)

    def save_configuration(self, config):
        """Save the settings (configs/eye_config.json) and, when one was
        typed, the API key (OS credential store), then close."""
        try:
            api_key = config.pop("api_key", None)
            from datetime import datetime, timezone
            config["last_validated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            self.config_manager.save_config(config)
            if api_key:
                self.credential_manager.store_credential("%s_api_key" % config["backend"], api_key)
            self.configuration_complete.emit(config)
            self.accept()
        except Exception as e:
            self._set_status("Could not save the configuration: %s" % e, _BAD)

    # ---- models ------------------------------------------------------------------------
    def _router_for_discovery(self):
        self._collect_fields()
        overrides = {}
        if self._typed_key():
            overrides["%s_api_key" % self.config.get("backend")] = self._typed_key()
        from eye.services.model_router import ModelRouter
        return ModelRouter(dict(self.config), _OverlayCredentials(self.credential_manager, overrides))

    def _detect_models(self):
        """Ask the provider / server for its models (the key under test is used
        from memory - it is not stored)."""
        backend = self.config.get("backend")
        if self.config.get("integration_type") == "cloud_api" and not (
                self._typed_key() or self._key_stored()):
            self.form_message.setText("Enter the API key first - the provider lists models only "
                                      "for a valid key.")
            return
        self.form_message.setText("Asking %s for its models..." % provider_label(backend))
        self.form_message.repaint()
        from eye.services.context_window_registry import curated_models, recommended_models
        try:
            available = self._router_for_discovery().backend.list_models() or []
        except Exception as e:
            available = []
            self.form_message.setText(explain_failure(str(e), self.config.get("integration_type")))
            if not curated_models(backend):
                return
        merged = list(available)
        for m in curated_models(backend):
            if m not in merged:
                merged.append(m)
        if not merged:
            self.form_message.setText(
                "No models found. Is the server running with a model loaded?"
                if self.config.get("integration_type") == "local_api"
                else "No models found - check the key, or type the model name.")
            return
        if not available:
            self.form_message.setText("The live list was not available - showing the built-in list.")
        else:
            self.form_message.setText("")
        self._show_model_selection_dialog(merged, recommended=recommended_models(backend),
                                          title="Models - %s" % provider_label(backend))

    def _show_common_models(self):
        backend = self.config.get("backend")
        from eye.services.context_window_registry import curated_models, recommended_models
        models = curated_models(backend)
        if not models:
            self.form_message.setText("No built-in list for %s - use Detect."
                                      % provider_label(backend))
            return
        self._show_model_selection_dialog(list(models), recommended=recommended_models(backend),
                                          title="Common models - %s" % provider_label(backend))

    def _show_model_selection_dialog(self, models, recommended=None, title="Select Model",
                                     info_text=None):
        from PyQt5.QtWidgets import QListWidget, QListWidgetItem
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(520, 440)
        _wizard_sheet(dialog)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(20, 18, 20, 18)
        head = QLabel("%d models" % len(models))
        head.setObjectName("pageTitle")
        lay.addWidget(head)
        filt = QLineEdit()
        filt.setPlaceholderText("Filter...")
        lay.addWidget(filt)
        lst = QListWidget()
        rec = [m for m in (recommended or []) if m in models]
        for m in rec:
            item = QListWidgetItem("%s  (recommended)" % m)
            item.setData(Qt.UserRole, m)
            lst.addItem(item)
        for m in sorted(x for x in models if x not in rec):
            item = QListWidgetItem(m)
            item.setData(Qt.UserRole, m)
            lst.addItem(item)
        filt.textChanged.connect(lambda t: [lst.item(i).setHidden(t.lower() not in lst.item(i).text().lower())
                                            for i in range(lst.count())])
        lst.itemDoubleClicked.connect(lambda _i: dialog.accept())
        lay.addWidget(lst, 1)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        _variant(cancel, "ghost")
        cancel.clicked.connect(dialog.reject)
        pick = QPushButton("Use this model")
        _variant(pick, "primary")
        pick.clicked.connect(dialog.accept)
        row.addWidget(cancel)
        row.addWidget(pick)
        lay.addLayout(row)
        if dialog.exec_() == QDialog.Accepted and lst.selectedItems():
            chosen = lst.selectedItems()[0].data(Qt.UserRole)
            if "model_name" in self._fields:
                self._fields["model_name"].setText(chosen)
            self.config["model_name"] = chosen
            self.form_message.setText("")

    # ---- diagnostics -------------------------------------------------------------------
    def _on_run_diagnostics(self):
        if getattr(self, "_diag_worker", None) is not None:
            return
        self.diag_button.setText("Running diagnostics...")
        self.diag_button.setEnabled(False)
        worker = _DiagnosticsWorker(self.config_manager, self.credential_manager)
        self._diag_worker = worker
        worker.done.connect(self._on_diagnostics_done)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_diagnostics_done(self, results, error):
        self._diag_worker = None
        self.diag_button.setText("Run diagnostics")
        self.diag_button.setEnabled(True)
        if error or not results:
            QMessageBox.warning(self, "Diagnostics", "Diagnostics could not run:\n\n%s" % error)
            return
        self._show_diagnostics_results(results)

    def _show_diagnostics_results(self, results):
        from PyQt5.QtWidgets import QTextEdit
        dialog = QDialog(self)
        dialog.setWindowTitle("Eye AI diagnostics")
        dialog.setMinimumSize(620, 520)
        _wizard_sheet(dialog)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(20, 18, 20, 18)
        t = QLabel("Eye AI diagnostics")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        report = QTextEdit()
        report.setReadOnly(True)
        if _site is not None:
            report.setStyleSheet(_site.log_view_sheet())
            _site.keep_style(report)

        def mark(status):
            return "#10B981" if status == "PASS" else "#F59E0B"
        ui = results.get("ui", {})
        html = "<p><b style='color:%s'>[%s] %s</b><br>%s</p>" % (
            mark(ui.get("status")), ui.get("status"), _esc(ui.get("name")), _esc(ui.get("message")))
        html += "<h3>Backend SDKs</h3><ul>" + "".join(
            "<li><span style='color:%s'>%s</span>: %s</li>"
            % (mark(s.get("status")), _esc(s.get("name")), _esc(s.get("message")))
            for s in results.get("sdks", [])) + "</ul>"
        cfg = results.get("config", {})
        html += "<h3>Configuration</h3><p><b style='color:%s'>[%s]</b> %s</p>" % (
            mark(cfg.get("status")), cfg.get("status"), _esc(cfg.get("message")))
        env = results.get("environment", {})
        html += "<h3>Environment</h3><p>Python %s<br>%s</p>" % (
            _esc(env.get("python_version")), _esc(env.get("platform")))
        report.setHtml(html)
        lay.addWidget(report, 1)
        close = QPushButton("Close")
        _variant(close, "ghost")
        close.clicked.connect(dialog.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
        dialog.exec_()


def _esc(text):
    s = "" if text is None else str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
