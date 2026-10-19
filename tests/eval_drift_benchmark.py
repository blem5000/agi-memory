"""Comprehensive LongTerm-SWE Multi-Language Code-Drift Benchmark for agi-memory.

Stress tests drift detection across 20 distinct multi-language code evolution scenarios:
- Python (functions, methods, classes, signatures, async conversions, constants, deleted files)
- TypeScript / JavaScript (functions, classes, interfaces, signature shifts)
- Go (functions, structs, signatures)
- False-positive resistance (whitespace, formatting, docstrings, type annotations)
"""
import _isolate  # noqa: F401,E402  -- isolate paths before any memory imports
import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory import findings
from agi_memory.layers.code_layer import CodeLayer
from agi_memory.layers.session_layer import SessionLayer

BENCHMARK_SCENARIOS = [
    # --- Python Scenarios ---
    {
        "id": "py_01_body_logic_drift",
        "file": "payment/processor.py",
        "initial": "def process_payment(amount: float, card_token: str) -> bool:\n    gateway = 'stripe_v2'\n    return True\n",
        "title": "Payment Gateway Logic",
        "text": "process_payment uses stripe_v2 gateway for authorization.",
        "updated": "def process_payment(amount: float, card_token: str) -> bool:\n    gateway = 'adyen_v3'\n    return True\n",
        "expected_drift": True,
        "expected_change": "body_drifted",
        "expected_symbol": "process_payment"
    },
    {
        "id": "py_02_signature_param_added",
        "file": "auth/tokens.py",
        "initial": "def generate_token(user_id: str) -> str:\n    return f'token_{user_id}'\n",
        "title": "Token Generation",
        "text": "generate_token takes user_id and generates bearer token.",
        "updated": "def generate_token(user_id: str, tenant_id: str = 'default') -> str:\n    return f'token_{tenant_id}_{user_id}'\n",
        "expected_drift": True,
        "expected_change": "signature_drifted",
        "expected_symbol": "generate_token"
    },
    {
        "id": "py_03_file_deleted",
        "file": "legacy/old_worker.py",
        "initial": "def run_worker():\n    return 'done'\n",
        "title": "Legacy Worker Rule",
        "text": "Ping legacy old_worker before running batch jobs.",
        "updated": None,
        "expected_drift": True,
        "expected_change": "deleted",
        "expected_symbol": None
    },
    {
        "id": "py_04_docstring_whitespace_negative",
        "file": "utils/math_helpers.py",
        "initial": "def calculate_tax(amount: float, rate: float = 0.1) -> float:\n    '''Old docstring.'''\n    return amount * rate\n",
        "title": "Tax Calculation Helper",
        "text": "calculate_tax multiplies amount by rate.",
        "updated": "def calculate_tax(amount: float, rate: float = 0.1) -> float:\n    '''Updated docstring with extensive comments and examples.'''\n    \n    # Internal comment\n    return amount * rate\n",
        "expected_drift": False,
        "expected_change": None,
        "expected_symbol": None
    },
    {
        "id": "py_05_symbol_removed",
        "file": "api/endpoints.py",
        "initial": "def get_status():\n    return 'ok'\n\ndef get_health_v1():\n    return 'healthy'\n",
        "title": "Health Endpoint Check",
        "text": "Health checks run against get_health_v1 endpoint.",
        "updated": "def get_status():\n    return 'ok'\n",
        "expected_drift": True,
        "expected_change": "removed",
        "expected_symbol": "get_health_v1"
    },
    {
        "id": "py_06_async_def_conversion",
        "file": "storage/client.py",
        "initial": "def fetch_blob(bucket: str, key: str) -> bytes:\n    return b'data'\n",
        "title": "Blob Fetcher Sync",
        "text": "fetch_blob reads synchronously from storage bucket.",
        "updated": "async def fetch_blob(bucket: str, key: str) -> bytes:\n    return b'data'\n",
        "expected_drift": True,
        "expected_change": "signature_drifted",
        "expected_symbol": "fetch_blob"
    },
    {
        "id": "py_07_class_method_signature",
        "file": "db/session.py",
        "initial": "class Database:\n    def connect(self, url: str):\n        return True\n",
        "title": "Database Connect Method",
        "text": "Database.connect takes url connection string.",
        "updated": "class Database:\n    def connect(self, url: str, timeout: int = 30):\n        return True\n",
        "expected_drift": True,
        "expected_change": "signature_drifted",
        "expected_symbol": "connect"
    },
    {
        "id": "py_08_class_method_body_drift",
        "file": "cache/lru.py",
        "initial": "class CacheManager:\n    def get_or_set(self, k: str, v: str) -> str:\n        return v\n",
        "title": "Cache Get Or Set",
        "text": "CacheManager.get_or_set provides write-through cache.",
        "updated": "class CacheManager:\n    def get_or_set(self, k: str, v: str) -> str:\n        if not k:\n            raise ValueError('empty key')\n        return v\n",
        "expected_drift": True,
        "expected_change": "body_drifted",
        "expected_symbol": "get_or_set"
    },
    {
        "id": "py_09_return_type_annotation",
        "file": "validation/schemas.py",
        "initial": "def validate_user(payload: dict) -> bool:\n    return True\n",
        "title": "User Schema Validation",
        "text": "validate_user returns boolean status.",
        "updated": "def validate_user(payload: dict) -> tuple[bool, str]:\n    return (True, '')\n",
        "expected_drift": True,
        "expected_change": "signature_drifted",
        "expected_symbol": "validate_user"
    },
    {
        "id": "py_10_constant_value_changed",
        "file": "config/constants.py",
        "initial": "MAX_RETRIES = 3\nDEFAULT_TIMEOUT = 5\n",
        "title": "Max Retries Constant",
        "text": "MAX_RETRIES is set to 3 across all worker queues.",
        "updated": "MAX_RETRIES = 10\nDEFAULT_TIMEOUT = 5\n",
        "expected_drift": True,
        "expected_change": "body_drifted",
        "expected_symbol": "MAX_RETRIES"
    },
    # --- TypeScript / JavaScript Scenarios ---
    {
        "id": "ts_11_function_signature_drift",
        "file": "src/frontend/api.ts",
        "initial": "export function fetchUsers(page: number): Promise<User[]> {\n  return fetch('/api/users');\n}\n",
        "title": "Fetch Users API",
        "text": "fetchUsers accepts page number and returns user array.",
        "updated": "export function fetchUsers(page: number, limit: number = 20): Promise<User[]> {\n  return fetch('/api/users');\n}\n",
        "expected_drift": True,
        "expected_change": "signature_drifted",
        "expected_symbol": "fetchUsers"
    },
    {
        "id": "ts_12_class_method_signature",
        "file": "src/services/logger.ts",
        "initial": "export class LoggerService {\n  logMessage(msg: string) {\n    console.log(msg);\n  }\n}\n",
        "title": "Logger Service Message",
        "text": "LoggerService.logMessage prints msg to console.",
        "updated": "export class LoggerService {\n  logMessage(msg: string, level: string = 'info') {\n    console.log(`[${level}] ${msg}`);\n  }\n}\n",
        "expected_drift": True,
        "expected_change": "signature_drifted",
        "expected_symbol": "logMessage"
    },
    {
        "id": "ts_13_class_removed",
        "file": "src/deprecated/old_client.ts",
        "initial": "export class OldClient {\n  sendRequest() {}\n}\n",
        "title": "Old Client Deprecation",
        "text": "OldClient wraps legacy REST endpoints.",
        "updated": "// Entire class removed in refactor\nexport const VERSION = 2;\n",
        "expected_drift": True,
        "expected_change": "removed",
        "expected_symbol": "sendRequest"
    },
    {
        "id": "ts_14_formatting_only_negative",
        "file": "src/utils/format.ts",
        "initial": "export function formatCurrency(amount: number): string {\n  return '$' + amount.toFixed(2);\n}\n",
        "title": "Currency Formatter",
        "text": "formatCurrency prefixes dollar sign.",
        "updated": "export function formatCurrency(amount: number): string {\n  // Formats dollar currency\n  return '$' + amount.toFixed(2);\n}\n",
        "expected_drift": False,
        "expected_change": None,
        "expected_symbol": None
    },
    # --- Go Scenarios ---
    {
        "id": "go_15_function_signature_drift",
        "file": "pkg/auth/token.go",
        "initial": "package auth\n\nfunc VerifyToken(token string) bool {\n    return len(token) > 0\n}\n",
        "title": "Go VerifyToken Handler",
        "text": "VerifyToken checks JWT signature and returns bool.",
        "updated": "package auth\n\nfunc VerifyToken(token string, issuer string) bool {\n    return len(token) > 0\n}\n",
        "expected_drift": True,
        "expected_change": "signature_drifted",
        "expected_symbol": "VerifyToken"
    },
    {
        "id": "go_16_struct_type_removed",
        "file": "pkg/models/user.go",
        "initial": "package models\n\ntype LegacyUser struct {\n    ID int\n}\n",
        "title": "Go LegacyUser Model",
        "text": "LegacyUser holds integer user ID.",
        "updated": "package models\n\ntype UserV2 struct {\n    UUID string\n}\n",
        "expected_drift": True,
        "expected_change": "removed",
        "expected_symbol": "LegacyUser"
    },
    {
        "id": "go_17_function_signature_drift",
        "file": "pkg/crypto/hash.go",
        "initial": "package crypto\n\nfunc ComputeHash(input string) string {\n    return \"md5_\" + input\n}\n",
        "title": "Go ComputeHash Alg",
        "text": "ComputeHash generates hash checksum.",
        "updated": "package crypto\n\nfunc ComputeHash(input string, salt string) string {\n    return \"sha256_\" + input + salt\n}\n",
        "expected_drift": True,
        "expected_change": "signature_drifted",
        "expected_symbol": "ComputeHash"
    },
    # --- Multi-File / Cross-Boundary Scenarios ---
    {
        "id": "py_18_multi_file_drift_a",
        "file": "pipeline/extract.py",
        "initial": "def extract_rows(source: str) -> list:\n    return [1, 2]\n",
        "title": "Pipeline Extract Rows",
        "text": "extract_rows reads rows from source uri.",
        "updated": "def extract_rows(source: str, batch_size: int = 100) -> list:\n    return [1, 2]\n",
        "expected_drift": True,
        "expected_change": "signature_drifted",
        "expected_symbol": "extract_rows"
    },
    {
        "id": "py_19_multi_file_drift_b",
        "file": "pipeline/transform.py",
        "initial": "def transform_row(row: dict) -> dict:\n    return row\n",
        "title": "Pipeline Transform Row",
        "text": "transform_row parses payload dictionary.",
        "updated": "def transform_row(row: dict) -> dict:\n    # Added normalization\n    row['normalized'] = True\n    return row\n",
        "expected_drift": True,
        "expected_change": "body_drifted",
        "expected_symbol": "transform_row"
    },
    {
        "id": "py_20_stable_anchor_negative",
        "file": "core/invariants.py",
        "initial": "def assert_invariants():\n    return True\n",
        "title": "System Invariants Check",
        "text": "assert_invariants guarantees system integrity.",
        "updated": "def assert_invariants():\n    return True\n",
        "expected_drift": False,
        "expected_change": None,
        "expected_symbol": None
    }
]


def run_benchmark(db_path: Path, work_dir: Path):
    proj = "swe-drift-20"
    code_layer = CodeLayer(project=proj, db_path=db_path)
    session_layer = SessionLayer(project=proj, db_path=db_path)

    cwd = os.getcwd()
    os.chdir(work_dir)
    try:
        mem_map = {}
        # Ingestion phase (Session 1)
        for sc in BENCHMARK_SCENARIOS:
            p = work_dir / sc["file"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(sc["initial"], encoding="utf-8")
            code_layer.index_file(sc["file"], project=proj, root_dir=work_dir)

            rec = session_layer.record(
                text=sc["text"],
                title=sc["title"],
                project=proj,
                origin="user-confirmed"
            )
            import sqlite3
            con = sqlite3.connect(db_path)
            con.execute("UPDATE observations SET files_modified = ? WHERE id = ?",
                        (json.dumps([sc["file"]]), rec["id"]))
            con.commit()
            con.close()
            mem_map[sc["id"]] = rec["id"]

        # Modification phase (Session 2)
        for sc in BENCHMARK_SCENARIOS:
            p = work_dir / sc["file"]
            if sc["updated"] is None:
                if p.exists():
                    p.unlink()
            else:
                p.write_text(sc["updated"], encoding="utf-8")

        # Verification phase (Session 3)
        results = []
        latencies = []
        for sc in BENCHMARK_SCENARIOS:
            oid = str(mem_map[sc["id"]])
            t0 = time.perf_counter()
            f_list = findings.for_observations([oid], project=proj, db_path=db_path)
            lat_ms = (time.perf_counter() - t0) * 1000
            latencies.append(lat_ms)

            drift_found = False
            drift_type = None
            detected_symbol = None
            if f_list:
                for line in f_list:
                    if "drifted" in line:
                        drift_found = True
                        m = re.search(r"references '([^']+)'", line)
                        if m:
                            detected_symbol = m.group(1)
                        if "body drifted" in line:
                            drift_type = "body_drifted"
                        elif "signature drifted" in line:
                            drift_type = "signature_drifted"
                        elif "removed" in line:
                            drift_type = "removed"
                    elif "no longer exist" in line:
                        drift_found = True
                        drift_type = "deleted"

            passed = (drift_found == sc["expected_drift"])
            if sc["expected_drift"]:
                if sc["expected_change"]:
                    passed = passed and (drift_type == sc["expected_change"])
                if sc["expected_symbol"]:
                    passed = passed and (detected_symbol == sc["expected_symbol"])

            results.append({
                "id": sc["id"],
                "file": sc["file"],
                "expected_drift": sc["expected_drift"],
                "detected_drift": drift_found,
                "expected_change": sc["expected_change"],
                "detected_change": drift_type,
                "expected_symbol": sc["expected_symbol"],
                "detected_symbol": detected_symbol,
                "passed": passed,
                "latency_ms": lat_ms,
                "findings": f_list
            })
    finally:
        os.chdir(cwd)

    return results, latencies


def main():
    parser = argparse.ArgumentParser(description="20-Scenario Multi-Language Code Drift Benchmark")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        db_path = root / "drift_eval_20.db"
        results, latencies = run_benchmark(db_path, root)

    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)
    mean_lat = sum(latencies) / len(latencies)
    p95_lat = sorted(latencies)[int(0.95 * len(latencies))]

    if args.json:
        print(json.dumps({
            "total_scenarios": total_count,
            "passed": passed_count,
            "accuracy": passed_count / total_count,
            "mean_latency_ms": mean_lat,
            "p95_latency_ms": p95_lat,
            "results": results
        }, indent=2))
        sys.exit(0 if passed_count == total_count else 1)

    print("\n=== LongTerm-SWE 20-Scenario Multi-Language Code-Drift Benchmark ===")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['latency_ms']:5.2f}ms :: {r['id']:<32} | {r['file']}")
        if r["findings"]:
            for f in r["findings"]:
                print(f"       -> Evidence: {f}")
        elif not r["expected_drift"]:
            print("       -> Clean: No false drift on docstring / formatting.")

    print(f"\nDrift Benchmark Accuracy: {passed_count}/{total_count} = {passed_count/total_count:.0%}")
    print(f"Mean Latency:             {mean_lat:.2f}ms (P95: {p95_lat:.2f}ms)")
    print(f"Token Consumption:        0 tokens (100% on-device SQLite AST)")
    sys.exit(0 if passed_count == total_count else 1)


if __name__ == "__main__":
    main()
