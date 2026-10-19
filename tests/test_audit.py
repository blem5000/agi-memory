import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory.audit import MemoryAudit, is_noise_record, is_test_project
from agi_memory.layers.session_layer import SessionLayer


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test_memory.db"
        self.vault = self.root / "vault"
        self.vault.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.tmp.cleanup)

        self.session_layer = SessionLayer(project="main-proj", db_path=self.db)
        self.auditor = MemoryAudit(db_path=self.db, vault_dir=self.vault)

    def test_test_project_identification(self):
        self.assertTrue(is_test_project("test-project"))
        self.assertTrue(is_test_project("test_repo"))
        self.assertTrue(is_test_project("p"))
        self.assertTrue(is_test_project("dummy"))
        self.assertFalse(is_test_project("agi-memory"))
        self.assertFalse(is_test_project("my-production-app"))

    def test_noise_record_identification(self):
        self.assertTrue(is_noise_record("", ""))
        self.assertTrue(is_noise_record("Project initialization", "session started"))
        self.assertTrue(is_noise_record("Caveman Ultra mode request", "talk like caveman"))
        self.assertFalse(is_noise_record("Database Connection Pool", "Fixed pool exhaustion by setting max_connections=20"))

    def test_scan_and_prune(self):
        # 1. Record valid memory
        self.session_layer.record(
            text="Use SQLite WAL mode for high concurrency.",
            title="SQLite concurrency pattern",
            project="main-proj",
            origin="user-confirmed"
        )

        # 2. Record synthetic test fixture memory
        self.session_layer.record(
            text="Temporary fixture observation.",
            title="Fixture test",
            project="test-fixture-proj",
            origin="test"
        )

        # 3. Record noise memory
        self.session_layer.record(
            text="Session init prompt",
            title="Project initialization",
            project="main-proj",
            origin="agent-inferred"
        )

        scan_before = self.auditor.scan()
        self.assertEqual(scan_before["total_observations"], 3)
        self.assertEqual(len(scan_before["test_fixtures"]), 1)
        self.assertEqual(len(scan_before["noise_records"]), 1)

        # Prune test fixtures & noise
        prune_res = self.auditor.prune_candidates(("test_fixtures", "noise_records"))
        self.assertEqual(prune_res["pruned_direct"], 2)

        scan_after = self.auditor.scan()
        self.assertEqual(scan_after["total_observations"], 1)
        self.assertEqual(len(scan_after["test_fixtures"]), 0)
        self.assertEqual(len(scan_after["noise_records"]), 0)


if __name__ == "__main__":
    unittest.main()
