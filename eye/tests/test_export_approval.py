"""
A report export asked for by the model goes through the investigator's approval
dialog and the chain of custody, exactly like the UI's Export button.

Before this, ``ContextManager._execute_tool`` ran ``handle_export_report``
directly on the worker thread: no dialog, no ledger line, and the
``hitl_callback`` it was handed was never used. A cancel in
``_show_hitl_dialog`` also read as approval, and the PDF path reported back
was not the file written.
"""

import os
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from eye.bridge.eye_bridge import EYEBridge
from eye.services.context_manager import ContextManager
from eye.services.report_engine import ReportEngine
from eye.services.report_handlers import ReportHandlers
from utils import custody


@pytest.fixture
def case(tmp_path):
    d = tmp_path / "case"
    (d / "logs").mkdir(parents=True)
    custody.set_case(str(d))
    yield d
    custody.set_case(None)


def _written(case_dir):
    """Every report file under the case (Reports/), and any cwd fallback."""
    reports = Path(case_dir) / "Reports"
    return sorted(p.name for p in reports.glob("*")
                  if p.is_file() and p.name != "reports_index.json") if reports.exists() else []


def _exports(case_dir):
    return [e for e in custody.read_ledger(str(case_dir)) if e.get("event") == "export written"]


def _cm(handler=None):
    """A ContextManager with only what _execute_tool touches."""
    cm = ContextManager.__new__(ContextManager)
    cm.logger = MagicMock()
    cm.tool_handlers = {"export_report": handler or MagicMock(name="handle_export_report")}
    return cm


# -- the model path: ContextManager._execute_tool -------------------------------------
def test_no_callback_refuses_and_writes_nothing(case):
    cm = _cm()
    out = cm._execute_tool({"name": "export_report", "parameters": {"format": "html"}})
    assert out["success"] is False
    assert "approval" in out["error"]
    cm.tool_handlers["export_report"].assert_not_called()
    assert _written(case) == [] and _exports(case) == []


def test_declined_writes_nothing(case):
    cm = _cm()
    cb = MagicMock(return_value=False)
    out = cm._execute_tool({"name": "export_report", "parameters": {"format": "html"}},
                           hitl_callback=cb)
    cb.assert_called_once_with("export_report", "html", {})
    assert out["result"]["approved"] is False and out["result"]["file_path"] is None
    assert "declined by investigator" in out["result"]["message"]
    cm.tool_handlers["export_report"].assert_not_called()
    assert _written(case) == [] and _exports(case) == []


def test_approved_returns_the_path_the_main_thread_wrote(case):
    cm = _cm()
    cb = MagicMock(return_value=r"C:\case\Reports\r.html")
    out = cm._execute_tool({"name": "export_report", "parameters": {"format": "html"}},
                           hitl_callback=cb)
    cb.assert_called_once_with("export_report", "html", {})
    assert out["success"] is True
    assert out["result"]["approved"] is True
    assert out["result"]["file_path"] == r"C:\case\Reports\r.html"
    cm.tool_handlers["export_report"].assert_not_called()


def test_md_is_normalised_and_bad_format_refused(case):
    cm = _cm()
    cb = MagicMock(return_value=False)
    cm._execute_tool({"name": "export_report", "parameters": {"format": "MD"}}, hitl_callback=cb)
    cb.assert_called_once_with("export_report", "markdown", {})
    out = cm._execute_tool({"name": "export_report", "parameters": {"format": "docx"}},
                           hitl_callback=cb)
    assert out["success"] is False and cb.call_count == 1


def test_argument_preferred_over_attribute_and_attribute_is_the_fallback(case):
    cm = _cm()
    attr_cb = MagicMock(return_value=False)
    arg_cb = MagicMock(return_value=False)
    cm.hitl_callback = attr_cb
    cm._execute_tool({"name": "export_report", "parameters": {"format": "pdf"}},
                     hitl_callback=arg_cb)
    arg_cb.assert_called_once_with("export_report", "pdf", {})
    attr_cb.assert_not_called()
    cm._execute_tool({"name": "export_report", "parameters": {"format": "pdf"}})
    attr_cb.assert_called_once_with("export_report", "pdf", {})


def test_export_failure_after_approval_is_reported_as_failure(case):
    cm = _cm()
    cb = MagicMock(return_value={"error": "weasyprint missing"})
    out = cm._execute_tool({"name": "export_report", "parameters": {"format": "pdf"}},
                           hitl_callback=cb)
    assert out["success"] is False and "weasyprint missing" in out["error"]


def test_handler_never_writes(case):
    """The handler is not a write path at all - not even when a caller claims
    approval - so it cannot write a report without a custody line."""
    engine = MagicMock()
    handlers = ReportHandlers(SimpleNamespace(report_engine=engine))
    for kwargs in ({}, {"approved_by_investigator": True}):
        out = handlers.handle_export_report({"format": "html"}, **kwargs)
        assert out["success"] is False and "approval" in out["error"]
    engine.export_html.assert_not_called()
    engine.export_pdf.assert_not_called()
    engine.export_markdown_file.assert_not_called()
    assert _written(case) == [] and _exports(case) == []


# -- the main thread: EYEBridge.export_report / _show_hitl_dialog ---------------------
class _Dialog:
    """Stands in for ReportExportApprovalDialog: records what it was shown."""
    approve = True
    shown = []

    def __init__(self, parent=None, format_type="html", file_size=0, destination_path=""):
        _Dialog.shown.append(destination_path)

    def exec_(self):
        return 1 if _Dialog.approve else 0

    def was_approved(self):
        return _Dialog.approve


@pytest.fixture
def bridge(case):
    engine = ReportEngine(str(case))
    b = EYEBridge(report_engine=engine)
    _Dialog.shown = []
    with patch("eye.ui.hitl_dialogs.ReportExportApprovalDialog", _Dialog):
        yield b


def test_bridge_approved_export_is_in_the_case_and_the_ledger(bridge, case):
    import json
    _Dialog.approve = True
    out = json.loads(bridge.export_report("html"))
    assert out["success"] is True and out["data"]["approved"] is True
    path = out["data"]["file_path"]
    # Written where the dialog said, inside the case's Reports folder
    assert _Dialog.shown == [path]
    assert Path(path).parent == case / "Reports" and Path(path).is_file()
    events = _exports(case)
    assert len(events) == 1
    f = events[0]["fields"]
    assert f["what"] == "Eye report (html)" and f["source"] == "ui"
    assert f["path"] == os.path.abspath(path)
    assert f["sha256"] == custody.sha256_file(path)[0]
    assert f["size"] == Path(path).stat().st_size
    assert custody.verify_ledger(str(case))["ok"]


def test_bridge_markdown_returns_the_real_path(bridge, case):
    import json
    _Dialog.approve = True
    out = json.loads(bridge.export_report("md"))
    path = out["data"]["file_path"]
    assert path.endswith(".md") and Path(path).is_file()
    assert _Dialog.shown == [path]
    assert _exports(case)[0]["fields"]["sha256"] == custody.sha256_file(path)[0]


def test_bridge_cancel_writes_nothing(bridge, case):
    import json
    _Dialog.approve = False
    out = json.loads(bridge.export_report("html"))
    assert out["data"]["approved"] is False and out["data"]["file_path"] is None
    assert _written(case) == [] and _exports(case) == []


def test_hitl_cancel_is_not_approval(bridge, case):
    _Dialog.approve = False
    loop = MagicMock()
    bridge._show_hitl_dialog("export_report", "html", {}, loop)
    assert loop.approved is False and loop.approved_data is False
    loop.quit.assert_called_once()
    assert _written(case) == [] and _exports(case) == []


def test_hitl_approval_writes_once_and_records_the_model_as_source(bridge, case):
    _Dialog.approve = True
    loop = MagicMock()
    bridge._show_hitl_dialog("export_report", "html", {}, loop)
    assert loop.approved is True
    assert isinstance(loop.approved_data, str) and Path(loop.approved_data).is_file()
    events = _exports(case)
    assert len(events) == 1 and events[0]["fields"]["source"] == "model"
    assert events[0]["fields"]["sha256"] == custody.sha256_file(loop.approved_data)[0]


def test_model_call_end_to_end_through_the_bridge(bridge, case):
    """The worker's callback, short-circuited onto this thread: the model's call
    reaches the same dialog, write and ledger line, and gets the real path back."""
    _Dialog.approve = True

    def cb(key, value, ctx):
        loop = MagicMock()
        bridge._show_hitl_dialog(key, value, ctx, loop)
        return loop.approved_data

    cm = _cm()
    out = cm._execute_tool({"name": "export_report", "parameters": {"format": "markdown"}},
                           hitl_callback=cb)
    assert out["success"] is True
    path = out["result"]["file_path"]
    assert Path(path).is_file() and Path(path).parent == case / "Reports"
    assert _exports(case)[0]["fields"]["path"] == os.path.abspath(path)
    cm.tool_handlers["export_report"].assert_not_called()


def _fake_pdf(self, html_content, output_path, metadata=None):
    with open(output_path, "wb") as f:
        f.write(b"%PDF-1.7\n" + html_content.encode("utf-8")[:64])
    return output_path


def test_bridge_pdf_lands_at_the_path_the_dialog_showed(bridge, case):
    """The PDF path was the one reported wrong before: it must be the file written."""
    import json
    _Dialog.approve = True
    with patch("eye.services.pdf_exporter.PDFExporter.export", _fake_pdf):
        out = json.loads(bridge.export_report("pdf"))
    assert out["success"] is True and out["data"]["approved"] is True
    path = out["data"]["file_path"]
    assert path.endswith(".pdf") and Path(path).is_file()
    assert _Dialog.shown == [path] and Path(path).parent == case / "Reports"
    events = _exports(case)
    assert len(events) == 1 and events[0]["fields"]["what"] == "Eye report (pdf)"
    assert events[0]["fields"]["sha256"] == custody.sha256_file(path)[0]


def test_hitl_pdf_failure_after_approval_is_an_error_not_a_file(bridge, case):
    """weasyprint failing (here OSError: its native libraries are missing) after
    the investigator approved: the model is told it failed, nothing is written."""
    _Dialog.approve = True

    def boom(self, html_content, output_path, metadata=None):
        raise OSError("cannot load library 'gobject-2.0-0'")

    loop = MagicMock()
    with patch("eye.services.pdf_exporter.PDFExporter.export", boom):
        bridge._show_hitl_dialog("export_report", "pdf", {}, loop)
    assert loop.approved is False
    assert isinstance(loop.approved_data, dict) and "gobject" in loop.approved_data["error"]
    assert not any(n.endswith(".pdf") for n in _written(case))
    assert _exports(case) == []
    loop.quit.assert_called_once()


def test_hitl_error_after_the_write_is_not_reported_as_declined(bridge, case):
    """Anything raising after a successful write must not tell the model 'declined'."""
    _Dialog.approve = True
    loop = MagicMock()
    real_export = bridge._export_report

    def written_then_raises(fmt, source="ui"):
        real_export(fmt, source=source)
        raise ValueError("bad json")

    with patch.object(bridge, "_export_report", written_then_raises):
        bridge._show_hitl_dialog("export_report", "html", {}, loop)
    assert loop.approved is False
    assert loop.approved_data == {"error": "bad json"}
    assert len(_exports(case)) == 1          # it was written and ledgered
    loop.quit.assert_called_once()


def test_ledger_line_goes_to_the_case_the_report_was_written_to(bridge, case, tmp_path):
    """Custody pointing at another case (or none) must not lose the line."""
    import json
    other = tmp_path / "other"
    (other / "logs").mkdir(parents=True)
    _Dialog.approve = True
    for custody_case in (str(other), None):
        custody.set_case(custody_case)
        out = json.loads(bridge.export_report("html"))
        assert out["success"] is True
    custody.set_case(str(case))
    assert len(_exports(case)) == 2
    assert _exports(other) == []


def test_index_records_the_report_type_not_the_file_stem(bridge, case):
    import json
    _Dialog.approve = True
    with patch("eye.services.pdf_exporter.PDFExporter.export", _fake_pdf):
        for fmt in ("html", "pdf", "markdown"):
            assert json.loads(bridge.export_report(fmt))["success"] is True
    index = json.loads((case / "Reports" / "reports_index.json").read_text(encoding="utf-8"))
    assert [e["report_type"] for e in index] == ["Forensic_Report"] * 3
    assert [e["format"] for e in index] == ["html", "pdf", "md"]


def test_same_second_exports_do_not_share_a_file(bridge, case):
    """Names are stamped to the second: a second export at the same stamp gets
    its own file, its own index entry and its own ledger line."""
    import json
    from eye.services.case_directory_manager import CaseDirectoryManager
    fixed = str(case / "Reports" / "UNKNOWN_Forensic_Report_20261018T044504.html")
    _Dialog.approve = True
    with patch.object(CaseDirectoryManager, "get_report_path", return_value=fixed):
        p1 = json.loads(bridge.export_report("html"))["data"]["file_path"]
        p2 = json.loads(bridge.export_report("html"))["data"]["file_path"]
    assert p1 == fixed and p2 != p1 and p2.endswith("_2.html")
    assert Path(p1).is_file() and Path(p2).is_file()
    assert _Dialog.shown == [p1, p2]
    assert [e["fields"]["path"] for e in _exports(case)] == [os.path.abspath(p1), os.path.abspath(p2)]


def test_path_shown_in_an_open_dialog_is_not_handed_out_again(bridge, case):
    """A second export asked for while the first dialog is still open (nested
    event loop) must not be shown - and then write - the same path."""
    import json
    from eye.services.case_directory_manager import CaseDirectoryManager
    fixed = str(case / "Reports" / "UNKNOWN_Forensic_Report_20261018T044504.md")
    inner = {}

    class Nesting(_Dialog):
        def exec_(self):
            if not inner:
                inner["started"] = True
                inner["out"] = json.loads(bridge.export_report("md"))
            return super().exec_()

    _Dialog.approve = True
    with patch("eye.ui.hitl_dialogs.ReportExportApprovalDialog", Nesting), \
            patch.object(CaseDirectoryManager, "get_report_path", return_value=fixed):
        outer = json.loads(bridge.export_report("md"))
    assert outer["data"]["file_path"] == fixed
    assert inner["out"]["data"]["file_path"] == fixed[:-3] + "_2.md"
    assert len(_exports(case)) == 2


# -- the worker wait cannot miss a fast answer ----------------------------------------
@pytest.mark.skipif(os.environ.get("CROWEYE_NO_SELF_ELEVATE") != "1",
                    reason="GUI test: set CROWEYE_NO_SELF_ELEVATE=1")
def test_resume_before_the_worker_waits_is_not_lost():
    """An answer that arrives before the worker enters loop.exec_() (an export
    that fails fast) must still release it."""
    from PyQt5.QtCore import QEventLoop, QThread, QTimer
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # keep a reference
    assert app is not None

    created, resumed, done = threading.Event(), threading.Event(), threading.Event()
    box = {}

    class Worker(QThread):                    # the real QueryWorker is a QThread
        def run(self):
            import time
            loop = QEventLoop()
            box["loop"] = loop
            created.set()
            resumed.wait(5)                   # the answer lands before exec_()
            QTimer.singleShot(5000, loop.quit)  # safety net so a failure cannot hang
            t0 = time.time()
            loop.exec_()
            box["waited"] = time.time() - t0
            done.set()

    w = Worker()
    w.start()
    assert created.wait(5)
    EYEBridge._resume_worker(box["loop"])
    resumed.set()
    assert done.wait(10)
    w.wait(5000)
    assert box["waited"] < 2.0, "quit was lost; the worker only woke on the safety timer"
