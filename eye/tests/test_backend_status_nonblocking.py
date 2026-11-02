"""Opening the Eye never waits on the model backend.

The Eye's "Loading forensic context" screen waited for get_backend_status,
which ran validate_connectivity on the GUI thread: up to 30 s of CLI probes,
or ten minutes for a cloud SDK with its default limits, with all of Crow-Eye
frozen. The check now runs on a worker (start_backend_check) and reports
through backend_status_changed:

  returns at once      even when the backend never answers
  says it is waiting   'checking' with the seconds waited, every second
  says why it failed   the backend's own reason in plain words (last_error),
                       and an SDK exception turned into a sentence
  connects             'connected' when the backend answers
  an SDK error         describe_backend_error names the cause and keeps the class
"""
import json
import os
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtCore, QtWidgets  # noqa: E402

from eye.backends.base import describe_backend_error  # noqa: E402
from eye.bridge.eye_bridge import EYEBridge  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Backend:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.last_error = ""
        self.release = threading.Event()

    def validate_connectivity(self):
        if self.behaviour == "hang":
            self.release.wait(10)
            return False
        if self.behaviour == "refused":
            self.last_error = "The API key was refused - check it in Settings -> Eye AI."
            return False
        if self.behaviour == "raises":
            raise TimeoutError("read timed out")
        return True


class _Router:
    def __init__(self, backend):
        self.backend = backend
        self.config = {"backend": "anthropic", "model_name": "claude-haiku-5-5",
                       "integration_type": "cloud_api"}

    def validate_connectivity(self):
        return self.backend.validate_connectivity()


class _CM:
    def __init__(self, router):
        self.model_router = router


def _bridge(behaviour):
    backend = _Backend(behaviour)
    bridge = EYEBridge(context_manager=_CM(_Router(backend)))
    seen = []
    bridge.backend_status_changed.connect(lambda s: seen.append(json.loads(s)))
    return bridge, backend, seen


def _pump(app, seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return False


def test_a_hanging_backend_never_blocks_and_says_it_is_waiting(app):
    bridge, backend, seen = _bridge("hang")
    t = time.monotonic()
    first = json.loads(bridge.start_backend_check())
    assert time.monotonic() - t < 0.5
    assert first["data"]["state"] == "checking"
    # get_backend_status during the check: the cached state, at once
    t = time.monotonic()
    snap = json.loads(bridge.get_backend_status())["data"]
    assert time.monotonic() - t < 0.2 and snap["state"] == "checking"
    _pump(app, 2.5)
    ticks = [s for s in seen if s["state"] == "checking" and s["seconds"] >= 1]
    assert ticks, seen
    backend.release.set()
    assert _pump(app, 5, until=lambda: seen and seen[-1]["state"] == "failed")
    assert seen[-1]["detail"]


def test_a_refused_key_is_said_in_words(app):
    bridge, _b, seen = _bridge("refused")
    bridge.start_backend_check()
    assert _pump(app, 5, until=lambda: seen and seen[-1]["state"] == "failed")
    assert "API key was refused" in seen[-1]["detail"]
    assert seen[-1]["model"] == "claude-haiku-5-5"


def test_an_exception_becomes_a_sentence(app):
    bridge, _b, seen = _bridge("raises")
    bridge.start_backend_check()
    assert _pump(app, 5, until=lambda: seen and seen[-1]["state"] == "failed")
    assert "did not answer in time" in seen[-1]["detail"]


def test_a_backend_that_answers_connects(app):
    bridge, _b, seen = _bridge("ok")
    bridge.start_backend_check()
    assert _pump(app, 5, until=lambda: seen and seen[-1]["state"] == "connected")
    assert seen[-1]["connected"] is True


def test_no_backend_is_not_configured(app):
    bridge = EYEBridge(context_manager=None)
    data = json.loads(bridge.start_backend_check())["data"]
    assert data["state"] == "not_configured"


@pytest.mark.parametrize("exc,words", [
    (type("AuthenticationError", (Exception,), {})("invalid x-api-key"), "API key was refused"),
    (type("NotFoundError", (Exception,), {})("model: claude-nope"), "model was not found"),
    (type("RateLimitError", (Exception,), {})("429"), "rate-limiting"),
    (type("APIConnectionError", (Exception,), {})("dns"), "Could not reach"),
])
def test_sdk_errors_are_named(exc, words):
    text = describe_backend_error(exc)
    assert words in text and type(exc).__name__ in text


def test_sampling_is_not_sent_to_models_that_reject_it():
    from eye.backends.cloud_api.anthropic_backend import sampling_allowed
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1",
                  "claude-opus-4-8", "claude-opus-4-7"):
        assert not sampling_allowed(model), model
    for model in ("claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6"):
        assert sampling_allowed(model), model
