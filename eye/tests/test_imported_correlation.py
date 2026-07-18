"""
Tests for analyzing imported evidence alongside native databases:

* Crow-Eye's auto-created Correlation feathers are SKIPPED by Eye discovery (no
  duplicate-data analysis); imported evidence is still discovered.
* Imported DBs are labeled "Imported Evidence" (distinct manifest category).
* `correlate_imported_evidence` deterministically finds shared identities (+ timestamp
  proximity) between imported and native artifacts, and reports none when independent.
"""

import os
import sqlite3
import tempfile
import types
import unittest

from correlation_engine.feather.importer import FeatherImporter
from eye.services.database_service import ForensicDatabaseService
from eye.services.forensic_handlers import ForensicHandlers


def _mk_db(path, table, columns_sql, rows):
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {table}({columns_sql})")
    conn.executemany(
        f"INSERT INTO {table} VALUES ({','.join('?' for _ in rows[0])})", rows) if rows else None
    conn.commit()
    conn.close()


class TestFeatherSkipAndLabel(unittest.TestCase):
    def setUp(self):
        self.case = tempfile.mkdtemp(prefix="isk_")
        self.art = os.path.join(self.case, "Target_Artifacts")
        os.makedirs(self.art)
        # native artifact
        _mk_db(os.path.join(self.art, "prefetch_data.db"), "prefetch_data",
               "executable_name TEXT, filename TEXT, last_executed TEXT",
               [("cmd.exe", r"C:\Windows\System32\cmd.exe", "2024-05-01 08:05:00")])
        # imported evidence
        imp_dir = os.path.join(self.art, "Imported_Evidence")
        os.makedirs(imp_dir)
        _mk_db(os.path.join(imp_dir, "vpn_logins.db"), "vpn_logins",
               "Timestamp TEXT, user TEXT", [("2024-05-01 08:00:00", "alice")])
        # correlation feather (auto-created; must be skipped)
        feath = os.path.join(self.art, "Correlation", "feathers")
        os.makedirs(feath)
        _mk_db(os.path.join(feath, "prefetch.db"), "prefetch",
               "executable_name TEXT", [("cmd.exe",)])

        self.ds = ForensicDatabaseService(self.art)

    def _by_name(self):
        return {d["name"]: d for d in self.ds.discover_databases() if d.get("accessible")}

    def test_correlation_feather_skipped(self):
        cats = [d["category"] for d in self.ds.discover_databases()]
        self.assertNotIn("Correlation Feather", cats)
        # the feather file itself is not surfaced
        names = {d["name"] for d in self.ds.discover_databases()}
        # prefetch.db (the feather) must not appear; prefetch_data.db (native) should
        self.assertNotIn("prefetch.db", names)

    def test_imported_labeled(self):
        d = self._by_name().get("vpn_logins.db")
        self.assertIsNotNone(d)
        self.assertEqual(d["category"], "Imported Evidence")
        self.assertTrue(d["display_name"].startswith("Imported:"))

    def test_native_not_duplicated(self):
        names = [d["name"] for d in self.ds.discover_databases() if d.get("accessible")]
        self.assertEqual(names.count("prefetch_data.db"), 1)


class TestCorrelateImportedEvidence(unittest.TestCase):
    def _build(self, native_rows, csv_text):
        case = tempfile.mkdtemp(prefix="ico_")
        art = os.path.join(case, "Target_Artifacts")
        os.makedirs(art)
        _mk_db(os.path.join(art, "prefetch_data.db"), "prefetch_data",
               "executable_name TEXT, filename TEXT, last_executed TEXT", native_rows)
        csv_path = os.path.join(case, "edr.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(csv_text)
        self.assertTrue(FeatherImporter(art).import_file(csv_path)["ok"])
        ds = ForensicDatabaseService(art)
        cm = types.SimpleNamespace(database_service=ds, search_service=None,
                                   correlation_service=None)
        return ForensicHandlers(cm)

    def test_correlation_found_with_provenance(self):
        fh = self._build(
            native_rows=[("cmd.exe", r"C:\Windows\System32\cmd.exe", "2024-05-01 08:05:00")],
            csv_text="Timestamp,filename,user\n2024-05-01 08:04:30,cmd.exe,alice\n",
        )
        res = fh.correlate_imported_evidence_core()
        self.assertTrue(res["success"])
        self.assertTrue(res["correlation_found"])
        m = res["identity_matches"][0]
        self.assertEqual(m["value"], "cmd.exe")
        hit = m["native_hits"][0]
        self.assertEqual(hit["database"], "prefetch_data.db")
        self.assertEqual(hit["table"], "prefetch_data")
        self.assertTrue(hit["temporal_match"])  # 08:04:30 vs 08:05:00 within 60 min

    def test_no_correlation_when_independent(self):
        fh = self._build(
            native_rows=[("notepad.exe", r"C:\notepad.exe", "2024-05-02 10:00:00")],
            csv_text="Timestamp,filename,user\n2024-05-05 00:00:00,zzz_unique_binary.exe,bob\n",
        )
        res = fh.correlate_imported_evidence_core()
        self.assertTrue(res["success"])
        self.assertFalse(res["correlation_found"])
        self.assertEqual(res["identity_matches"], [])

    def test_no_imported_evidence_is_noop(self):
        case = tempfile.mkdtemp(prefix="ino_")
        art = os.path.join(case, "Target_Artifacts")
        os.makedirs(art)
        _mk_db(os.path.join(art, "prefetch_data.db"), "prefetch_data",
               "executable_name TEXT", [("cmd.exe",)])
        cm = types.SimpleNamespace(database_service=ForensicDatabaseService(art),
                                   search_service=None, correlation_service=None)
        res = ForensicHandlers(cm).correlate_imported_evidence_core()
        self.assertTrue(res["success"])
        self.assertFalse(res["correlation_found"])
        self.assertEqual(res["imported_databases"], [])

    def test_tool_param_parsing(self):
        fh = self._build(
            native_rows=[("cmd.exe", r"C:\cmd.exe", "2024-05-01 08:05:00")],
            csv_text="Timestamp,filename,user\n2024-05-01 08:04:30,cmd.exe,alice\n",
        )
        res = fh.handle_correlate_imported_evidence({"max_values": "10", "time_window_minutes": "30"})
        self.assertTrue(res["success"])
        self.assertTrue(res["correlation_found"])


if __name__ == "__main__":
    unittest.main()
