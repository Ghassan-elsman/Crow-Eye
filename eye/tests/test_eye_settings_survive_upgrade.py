"""The Eye's settings live in the per-user folder, so an MSI upgrade keeps them.

2026-11-03: eye_config.json and the model probe cache resolved to the EXE's
`_internal\\configs`. A major upgrade uninstalls the old product's files, so every
upgrade sent the investigator back to first-run setup. Shipped files (schema,
presets, llm_config.json, knowledge base) stay with the app.
"""
import json
import sys
from pathlib import Path

import pytest

from config import case_history_manager
from eye.services import config_manager as cm

SETUP = {"integration_type": "local_cli", "backend": "claude_code", "model_name": "sonnet"}


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    d = tmp_path / "AppData" / "CrowEye" / "config"
    monkeypatch.setattr(case_history_manager, "default_config_dir", lambda: str(d))
    return d


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """A fake installed EXE: Program Files\\Crow-Eye\\CrowEye.exe with _internal."""
    app = tmp_path / "Program Files" / "Crow-Eye"
    meipass = app / "_internal"
    (meipass / "configs").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "CrowEye.exe"))
    # the repo's own configs must not be the one found
    monkeypatch.setattr(cm, "_legacy_config_candidates",
                        lambda: [meipass / "configs" / "eye_config.json",
                                 app / "configs" / "eye_config.json"])
    return app


def test_settings_are_saved_in_the_user_folder_not_the_bundle(user_dir, frozen):
    mgr = cm.ConfigManager()
    assert mgr.config_path == user_dir / "eye_config.json"
    # the schema still ships with the app
    assert mgr.schema_path.parent == cm._default_config_dir()
    mgr.config_path.write_text(json.dumps(SETUP), encoding="utf-8")
    assert not (frozen / "_internal" / "configs" / "eye_config.json").exists()
    assert cm.ConfigManager().load_config()["model_name"] == "sonnet"


def test_the_old_setup_is_copied_once_from_the_bundle(user_dir, frozen):
    old = frozen / "_internal" / "configs" / "eye_config.json"
    old.write_text(json.dumps(SETUP), encoding="utf-8")
    p = cm.user_config_path()
    assert json.loads(p.read_text(encoding="utf-8"))["backend"] == "claude_code"
    assert old.exists()                                   # the old file is left as it was
    # a later change is not overwritten by the old copy
    p.write_text(json.dumps(dict(SETUP, model_name="opus")), encoding="utf-8")
    assert json.loads(cm.user_config_path().read_text(encoding="utf-8"))["model_name"] == "opus"


def test_a_partial_copy_beside_the_exe_is_not_taken(user_dir, frozen):
    (frozen / "configs").mkdir()
    (frozen / "configs" / "eye_config.json").write_text(
        json.dumps({"context_window": {"max_total_tokens": 8192}}), encoding="utf-8")
    assert not cm.user_config_path().exists()


def test_the_bundle_copy_wins_over_the_one_beside_the_exe(user_dir, frozen):
    (frozen / "_internal" / "configs" / "eye_config.json").write_text(json.dumps(SETUP), encoding="utf-8")
    (frozen / "configs").mkdir()
    (frozen / "configs" / "eye_config.json").write_text(
        json.dumps(dict(SETUP, model_name="stale")), encoding="utf-8")
    assert json.loads(cm.user_config_path().read_text(encoding="utf-8"))["model_name"] == "sonnet"


def test_every_reader_uses_the_same_file(user_dir, frozen):
    from config import eye_ai_settings
    from eye.services.context_window_config_manager import ContextWindowConfigManager
    import shutil
    shutil.copy2(Path(cm.__file__).resolve().parents[2] / "configs" / "context_window_presets.json",
                 frozen / "_internal" / "configs" / "context_window_presets.json")
    target = user_dir / "eye_config.json"
    assert eye_ai_settings.eye_config_path() == target
    cw = ContextWindowConfigManager()
    assert cw.eye_config_path == target
    assert cw.presets_path.parent == cm._default_config_dir()   # presets ship with the app
    from eye.services import context_manager
    assert context_manager._user_eye_config() == target


def test_the_probe_cache_and_embedding_cache_are_per_user(user_dir):
    from eye.services import tool_capability
    # conftest swaps _default_cache_path for the test session; read the real one
    src = Path(tool_capability.__file__).read_text(encoding="utf-8")
    assert 'user_config_dir() / "eye_tool_capability.json"' in src
    rag = Path(cm.__file__).with_name("rag_service.py").read_text(encoding="utf-8")
    assert 'user_config_dir() / "eye_embcache"' in rag


def test_an_explicit_folder_keeps_both_files_together(tmp_path):
    mgr = cm.ConfigManager(str(tmp_path))
    assert mgr.config_path == tmp_path / "eye_config.json"
    assert mgr.schema_path == tmp_path / "eye_config_schema.json"
