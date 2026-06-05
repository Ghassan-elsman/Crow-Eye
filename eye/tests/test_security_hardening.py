"""
Security-hardening tests (audit Pass 2):
- S1: web-fetch host allowlist (hostname, not substring) + scheme restriction.
- S2: report_add_image confines model-supplied paths to the case directory.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from eye.services.forensic_handlers import ForensicHandlers
from eye.services.report_handlers import ReportHandlers
from eye.services.internet_search_service import _require_http_url


class TestRequireHttpUrl(unittest.TestCase):
    def test_rejects_non_http_schemes_and_empty_host(self):
        for bad in ("file:///etc/passwd", "ftp://h/x", "data:text/plain,hi", "", "http://"):
            with self.assertRaises(ValueError):
                _require_http_url(bad)

    def test_allows_http_and_https(self):
        _require_http_url("http://a.com/p")
        _require_http_url("https://b.example/q")  # no raise


class TestFetchWebContentAllowlist(unittest.TestCase):
    def setUp(self):
        self.fh = ForensicHandlers.__new__(ForensicHandlers)
        self.fh.cm = MagicMock()
        self.fh.cm.internet_search_service.fetch_page_content.return_value = {"success": True, "content": "ok"}

    def _denied(self, url):
        res = self.fh.handle_fetch_web_content({"url": url})
        self.assertFalse(res.get("success"), f"should deny {url}")
        self.fh.cm.internet_search_service.fetch_page_content.assert_not_called()

    def _allowed(self, url):
        res = self.fh.handle_fetch_web_content({"url": url})
        self.assertTrue(res.get("success"), f"should allow {url}")

    def test_substring_bypass_denied(self):
        self._denied("http://crow-eye.com.attacker.com/")

    def test_query_substring_denied(self):
        self._denied("http://evil.test/?x=github.com")

    def test_file_scheme_denied(self):
        self._denied("file:///C:/secret/crow-eye.com.txt")

    def test_metadata_ip_denied(self):
        self._denied("http://169.254.169.254/?x=github.com")

    def test_legit_hosts_allowed(self):
        for good in ("https://github.com/x", "https://learn.microsoft.com/y",
                     "https://crow-eye.com/z", "https://lolbas-project.github.io/a"):
            self.fh.cm.internet_search_service.fetch_page_content.reset_mock()
            self._allowed(good)


class TestReportAddImagePathConfinement(unittest.TestCase):
    def setUp(self):
        self.case_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        self.rh = ReportHandlers.__new__(ReportHandlers)
        self.rh.cm = MagicMock()
        self.rh.cm.case_directory = self.case_dir
        self.rh.cm.report_engine.add_image.return_value = "blk1"

    def tearDown(self):
        shutil.rmtree(self.case_dir, ignore_errors=True)
        shutil.rmtree(self.outside_dir, ignore_errors=True)

    def _img(self, directory, name="exhibit.png"):
        p = os.path.join(directory, name)
        with open(p, "wb") as f:
            f.write(b"\x89PNG\r\n")
        return p

    def test_in_case_image_allowed(self):
        p = self._img(self.case_dir)
        res = self.rh.handle_report_add_image({"image_path": p})
        self.assertTrue(res.get("success"))
        self.rh.cm.report_engine.add_image.assert_called_once()

    def test_outside_case_denied(self):
        p = self._img(self.outside_dir)
        res = self.rh.handle_report_add_image({"image_path": p})
        self.assertFalse(res.get("success"))
        self.rh.cm.report_engine.add_image.assert_not_called()

    def test_non_image_extension_denied(self):
        p = os.path.join(self.case_dir, "secret.txt")
        with open(p, "w") as f:
            f.write("not an image")
        res = self.rh.handle_report_add_image({"image_path": p})
        self.assertFalse(res.get("success"))
        self.rh.cm.report_engine.add_image.assert_not_called()

    def test_missing_in_case_file_denied(self):
        res = self.rh.handle_report_add_image({"image_path": os.path.join(self.case_dir, "nope.png")})
        self.assertFalse(res.get("success"))
        self.rh.cm.report_engine.add_image.assert_not_called()


if __name__ == "__main__":
    unittest.main()
