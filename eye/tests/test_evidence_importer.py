"""
Tests for the external-evidence import feature:

* FeatherImporter converts CSV / JSON to feather-shaped SQLite (auto-detecting the
  primary timestamp) and copies real SQLite databases verbatim.
* TimelineBridge discovers those imported feathers and serves them on the timeline
  ('imported' artifact type) with working time-window filtering + time bounds.
* ContextManager.refresh_database_manifest invalidates the cached schema manifest so
  the Eye sees newly-imported databases.
"""

import json
import os
import sqlite3
import tempfile
import types
import unittest

from correlation_engine.feather.importer import FeatherImporter


class TestFeatherImporter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ev_imp_")
        self.artifacts = os.path.join(self.tmp, "Target_Artifacts")
        os.makedirs(self.artifacts, exist_ok=True)
        self.importer = FeatherImporter(self.artifacts)

    def _write(self, name, content, mode="w"):
        path = os.path.join(self.tmp, name)
        with open(path, mode, encoding=None if "b" in mode else "utf-8", newline="") as f:
            f.write(content)
        return path

    def test_csv_conversion(self):
        csv_path = self._write(
            "logins.csv",
            "Timestamp,User Name,Source IP,EventID\n"
            "2024-03-01 08:15:22,alice,10.0.0.5,4624\n"
            "2024-03-01T09:01:00,bob,10.0.0.9,4625\n",
        )
        r = self.importer.import_file(csv_path)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["source_type"], "csv")
        self.assertEqual(r["row_count"], 2)
        self.assertEqual(r["primary_timestamp"], "Timestamp")
        self.assertTrue(r["dest_db"].endswith(".db"))
        self.assertIn("Imported_Evidence", r["dest_db"])

        conn = sqlite3.connect(r["dest_db"])
        try:
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{r["table"]}")').fetchall()]
            self.assertIn("User_Name", cols)  # space sanitized to underscore
            # feather_metadata is stamped (so the engine/timeline can read the primary ts)
            keys = [k for (k,) in conn.execute("SELECT key FROM feather_metadata").fetchall()]
            self.assertIn(f"table:{r['table']}", keys)
            # timestamp normalized to ISO-8601
            ts = conn.execute(f'SELECT "Timestamp" FROM "{r["table"]}" ORDER BY "Timestamp" LIMIT 1').fetchone()[0]
            self.assertEqual(ts, "2024-03-01T08:15:22")
        finally:
            conn.close()

    def test_json_nested_conversion(self):
        json_path = self._write("procs.json", json.dumps({
            "meta": {"tool": "x"},
            "events": [
                {"created": "2024-03-01T08:16:00Z", "proc": {"name": "cmd.exe", "pid": 1234}, "args": ["/c"]},
                {"created": "2024-03-01T08:16:05Z", "proc": {"name": "powershell.exe", "pid": 5}, "args": []},
            ],
        }))
        r = self.importer.import_file(json_path)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["row_count"], 2)
        self.assertEqual(r["primary_timestamp"], "created")

        conn = sqlite3.connect(r["dest_db"])
        try:
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{r["table"]}")').fetchall()]
            self.assertIn("proc_name", cols)  # nested dict flattened
            self.assertIn("args", cols)       # list column preserved (JSON-encoded)
            args = conn.execute(f'SELECT args FROM "{r["table"]}" LIMIT 1').fetchone()[0]
            self.assertEqual(json.loads(args), ["/c"])
        finally:
            conn.close()

    def test_sqlite_copy_verbatim(self):
        db_path = os.path.join(self.tmp, "external.db")
        c = sqlite3.connect(db_path)
        c.execute("CREATE TABLE t(a TEXT, b INT)")
        c.execute("INSERT INTO t VALUES('x', 1)")
        c.commit(); c.close()

        r = self.importer.import_file(db_path)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["source_type"], "sqlite")
        self.assertEqual(r["table"], "t")
        self.assertEqual(r["row_count"], 1)

    def test_invalid_sqlite_rejected(self):
        bad = self._write("not_a_db.db", "this is not sqlite")
        r = self.importer.import_file(bad)
        self.assertFalse(r["ok"])
        self.assertIn("valid SQLite", r["error"])

    def test_unsupported_extension(self):
        p = self._write("evidence.xyz", "data")
        r = self.importer.import_file(p)
        self.assertFalse(r["ok"])
        self.assertIn("Unsupported", r["error"])

    def test_unique_dest_no_overwrite(self):
        csv_path = self._write("dup.csv", "time,name\n2024-01-01 00:00:00,a\n")
        r1 = self.importer.import_file(csv_path)
        r2 = self.importer.import_file(csv_path)
        self.assertTrue(r1["ok"] and r2["ok"])
        self.assertNotEqual(r1["dest_db"], r2["dest_db"])  # second gets a _2 suffix


class TestTimelineImportedLane(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ev_tl_")
        self.artifacts = os.path.join(self.tmp, "Target_Artifacts")
        os.makedirs(self.artifacts, exist_ok=True)
        csv_path = os.path.join(self.tmp, "vpn.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("Timestamp,User,Host\n")
            f.write("2024-05-01 08:00:00,alice,HOST1\n")
            f.write("2024-05-01 09:30:00,bob,HOST2\n")
            f.write("2024-05-03 12:00:00,alice,HOST1\n")
        self.assertTrue(FeatherImporter(self.artifacts).import_file(csv_path)["ok"])

        from timeline.timeline_bridge import TimelineBridge
        self.bridge = TimelineBridge(self.artifacts)

    def test_discovery(self):
        found = self.bridge._imported_feather_tables()
        self.assertEqual(len(found), 1)
        _db, table, ts_col, id_col = found[0]
        self.assertEqual(table, "vpn")
        self.assertEqual(ts_col, "Timestamp")
        self.assertEqual(id_col, "User")

    def test_time_bounds_include_imported(self):
        bounds = json.loads(self.bridge.getTimeBounds())
        self.assertIsNotNone(bounds["start"])
        self.assertIn("2024-05-01", bounds["start"])
        self.assertIn("2024-05-03", bounds["end"])

    def test_get_imported_data_and_filtering(self):
        allrows = json.loads(self.bridge.getImportedData("2024-04-01T00:00:00", "2024-06-01T00:00:00"))
        self.assertEqual(len(allrows), 3)
        ev = allrows[0]
        self.assertEqual(ev["artifact_type"], "imported")
        self.assertEqual(ev["source_db"], "vpn")
        self.assertIn("timestamp", ev)       # generic plotter reads this
        self.assertIn("display_name", ev)    # identity for correlation links

        narrow = json.loads(self.bridge.getImportedData("2024-05-01T00:00:00", "2024-05-02T00:00:00"))
        self.assertEqual(len(narrow), 2)


class TestManifestRefresh(unittest.TestCase):
    def test_refresh_clears_caches(self):
        from eye.services.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)  # avoid heavy __init__
        cm._db_manifest_cache = "STALE"
        cm.logger = types.SimpleNamespace(debug=lambda *a, **k: None, warning=lambda *a, **k: None)
        cleared = {"schema": False}

        class _Svc:
            _schema_cache = {("db", "t"): {"x": 1}}
        svc = _Svc()
        cm.database_service = svc

        cm.refresh_database_manifest()
        self.assertIsNone(cm._db_manifest_cache)
        self.assertEqual(len(svc._schema_cache), 0)


if __name__ == "__main__":
    unittest.main()
