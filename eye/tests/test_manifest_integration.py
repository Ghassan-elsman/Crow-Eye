"""
Integration test: the full discover_databases -> get_schema -> manifest chain,
exercised through the REAL ForensicDatabaseService (not a stub), proves the
system prompt is grounded in the actual DB schema (real tables + columns).
"""

import logging
import shutil
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path

try:
    from eye.services.database_service import ForensicDatabaseService
    from eye.services.context_manager import ContextManager
    _IMPORT_OK = True
except Exception:  # host DatabaseManager / deps unavailable
    _IMPORT_OK = False


@unittest.skipUnless(_IMPORT_OK, "ForensicDatabaseService/ContextManager unavailable")
class TestManifestIntegration(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # Use filenames the discovery registry recognizes.
        pf = sqlite3.connect(str(Path(self.dir) / "prefetch_data.db"))
        pf.execute("CREATE TABLE prefetch_data (executable_name TEXT, run_count INTEGER, "
                   "last_executed TEXT, run_times TEXT)")
        pf.execute("INSERT INTO prefetch_data VALUES ('REG.EXE', 244, '2026-06-01', '[]')")
        pf.commit(); pf.close()

        am = sqlite3.connect(str(Path(self.dir) / "amcache_data.db"))
        am.execute("CREATE TABLE InventoryApplication (name TEXT, publisher TEXT, install_date TEXT)")
        am.execute("CREATE TABLE InventoryApplicationFile (name TEXT, lower_case_long_path TEXT)")
        am.commit(); am.close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _manifest(self):
        svc = ForensicDatabaseService(self.dir)
        stub = types.SimpleNamespace(
            database_service=svc, logger=logging.getLogger("itest"), _db_manifest_cache=None
        )
        return ContextManager._build_database_manifest(stub)

    def test_real_service_manifest_has_columns(self):
        m = self._manifest()
        # Real columns surfaced through the real discover -> get_schema -> manifest chain.
        self.assertIn("prefetch_data(", m)
        self.assertIn("last_executed", m)
        self.assertNotIn("last_run_time", m)
        # install_date appears under InventoryApplication (its real owner).
        self.assertIn("install_date", m)
        ia = next((ln for ln in m.splitlines() if "InventoryApplication(" in ln), "")
        self.assertIn("install_date", ia)
        iaf = next((ln for ln in m.splitlines() if "InventoryApplicationFile(" in ln), "")
        self.assertNotIn("install_date", iaf)  # not on the wrong table


if __name__ == "__main__":
    unittest.main()
