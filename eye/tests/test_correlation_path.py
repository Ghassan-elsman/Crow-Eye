"""
Tests for CorrelationService correlation-DB path resolution.

The Correlation Engine writes results to
``<case>/Correlation/output/correlation_results.db`` but the service previously
looked only in the case root, so `database_exists()` always failed and
`query_correlation_results` answered "not found". These tests pin the canonical
path, the legacy fallback, and mid-session re-resolution.
"""

import os
import tempfile
import unittest
from pathlib import Path

from eye.services.correlation_service import CorrelationService


def _touch(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


class TestCorrelationPathResolution(unittest.TestCase):
    def setUp(self):
        self.case = Path(tempfile.mkdtemp())

    def test_canonical_output_path(self):
        canonical = self.case / "Correlation" / "output" / "correlation_results.db"
        _touch(canonical)
        svc = CorrelationService(self.case)
        self.assertEqual(svc.correlation_db_path, canonical)
        self.assertTrue(svc.database_exists())

    def test_legacy_root_path_fallback(self):
        legacy = self.case / "correlation_results.db"
        _touch(legacy)
        svc = CorrelationService(self.case)
        self.assertEqual(svc.correlation_db_path, legacy)
        self.assertTrue(svc.database_exists())

    def test_canonical_wins_over_legacy(self):
        canonical = self.case / "Correlation" / "output" / "correlation_results.db"
        legacy = self.case / "correlation_results.db"
        _touch(canonical)
        _touch(legacy)
        svc = CorrelationService(self.case)
        self.assertEqual(svc.correlation_db_path, canonical)

    def test_glob_fallback_for_variant_layout(self):
        variant = self.case / "Correlation" / "run1" / "correlation_results.db"
        _touch(variant)
        svc = CorrelationService(self.case)
        self.assertEqual(svc.correlation_db_path, variant)
        self.assertTrue(svc.database_exists())

    def test_missing_returns_canonical_for_clear_error(self):
        svc = CorrelationService(self.case)
        self.assertEqual(
            svc.correlation_db_path,
            self.case / "Correlation" / "output" / "correlation_results.db",
        )
        self.assertFalse(svc.database_exists())

    def test_reresolves_when_engine_runs_mid_session(self):
        # Opened before the engine ran -> not found...
        svc = CorrelationService(self.case)
        self.assertFalse(svc.database_exists())
        # ...engine writes results during the session...
        canonical = self.case / "Correlation" / "output" / "correlation_results.db"
        _touch(canonical)
        # ...and database_exists() now picks it up without a restart.
        self.assertTrue(svc.database_exists())
        self.assertEqual(svc.correlation_db_path, canonical)


if __name__ == "__main__":
    unittest.main()
