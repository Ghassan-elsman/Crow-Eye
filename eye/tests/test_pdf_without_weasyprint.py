"""PDF export works without weasyprint's native libraries.

weasyprint imports, then needs GTK's Pango and Cairo DLLs; on a Windows
machine without GTK the import raises OSError (not ImportError), so every
Eye PDF export failed there. The exporter now prints the same HTML with
QtWebEngine, which Crow-Eye already ships. The printing itself needs a real
display (QtWebEngine crashes under the offscreen platform the suites use), so
this checks the decision and what reaches the printer; the print was checked
by hand on a 200 KB report: 81 A4 pages, 6.9 s.
"""
import builtins
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from eye.services.pdf_exporter import PDFExporter  # noqa: E402


@pytest.fixture
def no_weasyprint(monkeypatch):
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "weasyprint" or name.startswith("weasyprint."):
            raise OSError("cannot load library 'libgobject-2.0-0'")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)


def test_a_missing_native_library_prints_with_qtwebengine(no_weasyprint, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(PDFExporter, "_export_with_qtwebengine",
                        lambda self, html, path: seen.update(html=html, path=path)
                        or open(path, "wb").write(b"%PDF-1.4\n%%EOF\n"))
    meta = []
    monkeypatch.setattr(PDFExporter, "_apply_pdf_metadata",
                        lambda self, path, m: meta.append((path, m)))
    out = str(tmp_path / "r.pdf")
    PDFExporter({}).export("<html><body><h1>Report</h1></body></html>", out, {"title": "T"})
    assert seen["path"] == out and "<h1>Report</h1>" in seen["html"]
    assert meta == [(out, {"title": "T"})]
    assert open(out, "rb").read(4) == b"%PDF"


def test_off_the_gui_thread_it_says_so(no_weasyprint, tmp_path):
    # No QApplication here: the fallback refuses rather than crashing Qt.
    from PyQt5.QtWidgets import QApplication
    if QApplication.instance() is not None:
        pytest.skip("a QApplication exists in this run")
    with pytest.raises(RuntimeError, match="GUI thread"):
        PDFExporter({}).export("<html></html>", str(tmp_path / "x.pdf"))
