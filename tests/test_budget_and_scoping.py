import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = _TESTS.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _isolate  # noqa: F401 -- must run before agi_memory resolves any path
import tempfile
import unittest

from agi_memory.layers.session_layer import SessionLayer
from agi_memory.recall import recall
from agi_memory.mcp_server import call_tool


class TestBudgetAndScoping(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_memory.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_multi_scope_tiering_and_shadowing(self):
        l1 = SessionLayer(db_path=self.db_path, project="service-alpha")
        # Global convention
        l1.record(
            text="Use structured logging with JSON format across all services",
            title="Logging Convention Global",
            project="*"
        )
        # Project specific convention
        l1.record(
            text="Use protobuf structured logging specifically for service-alpha",
            title="Logging Convention Service Alpha",
            project="service-alpha"
        )

        hits = l1.search("logging structured format", limit=10)
        self.assertGreaterEqual(len(hits), 2)
        # Project-specific record must outrank global record
        self.assertIn("service-alpha", hits[0].text)
        self.assertIn("[*]", hits[1].text)

    def test_core_blocks_global_scoping(self):
        l1 = SessionLayer(db_path=self.db_path, project="proj-beta")
        l1.pin_block(key="global_rule", content="Always run typecheck", project="*")
        l1.pin_block(key="local_rule", content="Use port 8080", project="proj-beta")

        blocks = l1.get_pinned_blocks(project="proj-beta")
        self.assertEqual(len(blocks), 2)
        # Project-specific block comes first due to scope shadowing
        self.assertEqual(blocks[0]["key"], "local_rule")
        self.assertEqual(blocks[1]["key"], "global_rule")

    def test_search_budgeting(self):
        l1 = SessionLayer(db_path=self.db_path, project="budget-proj")
        for i in range(5):
            l1.record(
                text=f"Observation {i}: " + ("x" * 200),
                title=f"Record {i}",
                project="budget-proj"
            )

        all_hits = l1.search("Observation", limit=5)
        self.assertEqual(len(all_hits), 5)

        # Restrict by max_bytes
        budgeted_hits = l1.search("Observation", limit=5, max_bytes=350)
        self.assertLess(len(budgeted_hits), 5)
        total_bytes = sum(len(h.text.encode("utf-8")) for h in budgeted_hits)
        self.assertLessEqual(total_bytes, 350)

    def test_mcp_recall_budgeting(self):
        l1 = SessionLayer(project="mcp-budget")
        for i in range(4):
            l1.record(
                text=f"Database connection parameter note {i}: " + ("abc " * 50),
                title=f"DB Config {i}",
                project="mcp-budget"
            )

        # Call tool without budget
        res_unbudgeted = call_tool("memory_recall", {"query": "database connection parameter", "project": "mcp-budget"})
        # Call tool with max_bytes budget
        res_budgeted = call_tool("memory_recall", {
            "query": "database connection parameter",
            "project": "mcp-budget",
            "max_bytes": 250
        })

        self.assertLess(len(res_budgeted.encode("utf-8")), len(res_unbudgeted.encode("utf-8")))
        self.assertLessEqual(len(res_budgeted.encode("utf-8")), 250)
        self.assertIn("... [budget reached]", res_budgeted)


if __name__ == "__main__":
    unittest.main()
