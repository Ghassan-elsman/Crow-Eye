"""
Tests that the always-present database manifest carries the REAL tables AND
columns (grounding SQL generation), so the model stops inventing identifiers
like `last_run_time` / `registry_data` / `install_date`.
"""

import logging
import types
import unittest

from eye.services.context_manager import ContextManager


class _FakeDBService:
    """Minimal stand-in for ForensicDatabaseService."""
    def __init__(self, dbs, schemas, fail=()):
        self._dbs = dbs
        self._schemas = schemas
        self._fail = set(fail)

    def discover_databases(self):
        return self._dbs

    def get_schema(self, name, table=None):
        if name in self._fail:
            return {"success": False, "database": name, "error": "locked"}
        return {"success": True, "database": name, "schema": self._schemas.get(name, {})}


def _stub(db_service):
    stub = types.SimpleNamespace()
    stub.database_service = db_service
    stub.logger = logging.getLogger("test-manifest")
    stub._db_manifest_cache = None
    return stub


class TestDatabaseManifest(unittest.TestCase):
    def _build(self, db_service, **kw):
        return ContextManager._build_database_manifest(_stub(db_service), **kw)

    def test_manifest_includes_real_tables_and_columns(self):
        svc = _FakeDBService(
            dbs=[{"name": "prefetch_data.db", "category": "Execution",
                  "tables": ["prefetch_data"], "accessible": True, "exists": True}],
            schemas={"prefetch_data.db": {
                "prefetch_data": ["executable_name", "run_count", "last_executed", "run_times"]}},
        )
        m = self._build(svc)
        self.assertIn("prefetch_data(", m)
        self.assertIn("last_executed", m)        # real column present
        self.assertNotIn("last_run_time", m)     # invented column never appears
        self.assertIn("ONLY these exact", m)     # grounding instruction in header

    def test_column_cap_applies(self):
        cols = [f"c{i}" for i in range(40)]
        svc = _FakeDBService(
            dbs=[{"name": "big.db", "category": "Artifact",
                  "tables": ["t"], "accessible": True, "exists": True}],
            schemas={"big.db": {"t": cols}},
        )
        m = self._build(svc, max_cols_per_table=12)
        self.assertIn("+28 more", m)             # 40 - 12
        self.assertIn("c0", m)
        self.assertNotIn("c39", m)

    def test_fallback_to_table_names_when_schema_fails(self):
        svc = _FakeDBService(
            dbs=[{"name": "locked.db", "category": "Artifact",
                  "tables": ["TableA", "TableB"], "accessible": True, "exists": True}],
            schemas={}, fail=("locked.db",),
        )
        m = self._build(svc)
        self.assertIn("TableA", m)
        self.assertIn("TableB", m)               # listed even without columns

    def test_skips_inaccessible_dbs(self):
        svc = _FakeDBService(
            dbs=[{"name": "gone.db", "category": "X", "tables": [], "accessible": False, "exists": False}],
            schemas={},
        )
        m = self._build(svc)
        self.assertNotIn("gone.db", m)


if __name__ == "__main__":
    unittest.main()
