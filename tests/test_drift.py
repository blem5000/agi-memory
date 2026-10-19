import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory import findings
from agi_memory.layers.code_layer import CodeLayer
from agi_memory.layers.session_layer import SessionLayer


class SymbolDriftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "drift_test.db"
        self.addCleanup(self.tmp.cleanup)

        self.session_layer = SessionLayer(project="test-proj", db_path=self.db)
        self.code_layer = CodeLayer(project="test-proj", db_path=self.db)

    def _index_file(self, rel_name: str, content: str):
        file_path = self.root / rel_name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            self.code_layer.index_file(rel_name, project="test-proj", root_dir=self.root)
        finally:
            os.chdir(cwd)
        return file_path

    def test_ast_hash_and_drift_detection(self):
        initial_code = """
def calculate_tax(amount: float) -> float:
    \"\"\"Docstring explaining tax calculation.\"\"\"
    rate = 0.15
    return amount * rate
"""
        src_path = self._index_file("tax.py", initial_code)

        # Confirm 0 drift initially
        drift_init = self.code_layer.detect_symbol_drift(["tax.py"], project="test-proj")
        self.assertEqual(len(drift_init), 0)

        # 1. Modify docstring and whitespace only - AST should NOT drift
        doc_only = """
def calculate_tax(amount: float) -> float:
    \"\"\"Updated new docstring with different explanation.\"\"\"
    
    rate = 0.15
    return amount * rate
"""
        src_path.write_text(doc_only, encoding="utf-8")
        drift_doc = self.code_layer.detect_symbol_drift(["tax.py"], project="test-proj")
        self.assertEqual(len(drift_doc), 0, "Docstring or whitespace change should not trigger AST drift")

        # 2. Modify actual logic (rate changed to 0.20) - AST SHOULD drift
        logic_changed = """
def calculate_tax(amount: float) -> float:
    \"\"\"Docstring.\"\"\"
    rate = 0.20
    return amount * rate
"""
        src_path.write_text(logic_changed, encoding="utf-8")
        drift_logic = self.code_layer.detect_symbol_drift(["tax.py"], project="test-proj")
        self.assertEqual(len(drift_logic), 1)
        self.assertEqual(drift_logic[0]["symbol"], "calculate_tax")
        self.assertEqual(drift_logic[0]["change"], "body_drifted")

        # 3. Modify signature - should report signature drift
        sig_changed = """
def calculate_tax(amount: float, jurisdiction: str = "US") -> float:
    rate = 0.20
    return amount * rate
"""
        src_path.write_text(sig_changed, encoding="utf-8")
        drift_sig = self.code_layer.detect_symbol_drift(["tax.py"], project="test-proj")
        self.assertEqual(len(drift_sig), 1)
        self.assertEqual(drift_sig[0]["symbol"], "calculate_tax")

    def test_findings_integration_with_drift(self):
        initial_code = """
def authenticate(token: str) -> bool:
    return token == "secret"
"""
        src_path = self._index_file("auth.py", initial_code)

        rec = self.session_layer.record(
            text="authenticate() validates bearer token against hardcoded secret.",
            title="Authentication logic",
            project="test-proj",
            origin="user-confirmed"
        )
        oid = str(rec["id"])

        # Attach file to observation
        con = sqlite3.connect(self.db)
        con.execute("UPDATE observations SET files_modified = ? WHERE id = ?",
                    (json.dumps(["auth.py"]), rec["id"]))
        con.commit()
        con.close()

        # Before modification: no findings
        f_before = findings.for_observations([oid], project="test-proj", db_path=self.db)
        self.assertEqual(f_before, [])

        # Modify implementation
        src_path.write_text("""
def authenticate(token: str) -> bool:
    # Changed implementation
    return check_jwt_signature(token)
""", encoding="utf-8")

        f_after = findings.for_observations([oid], project="test-proj", db_path=self.db)
        self.assertTrue(len(f_after) > 0)
        self.assertIn("authenticate", f_after[0])
        self.assertIn("drifted", f_after[0])


if __name__ == "__main__":
    unittest.main()
