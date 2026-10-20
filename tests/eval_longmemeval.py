"""LongMemEval 100-Session, 50-Query Comprehensive Long-Term Memory Benchmark Suite.

Evaluates agi-memory on a simulated 100-session developer horizon spanning 6 projects:
- 100 chronological developer sessions with timestamps, tags, and commit hashes.
- 50 diverse evaluation queries testing:
  1. Temporal Depth & Needle Retrieval (depths 1..95 sessions)
  2. Cascading Knowledge Updating & Supersession (single and multi-step supersessions)
  3. Multi-Session Multi-Hop Synthesis (combining facts across distant sessions)
  4. Distractor Resistance & Lexical Noise Immunity
  5. Temporal Event Ordering & Timeline Reasoning
- Metrics: Recall@1, Recall@3, Recall@5, MRR, latency distribution (Mean, P95, P99).
"""
import _isolate  # noqa: F401,E402  -- isolate paths before any memory imports
import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.layers.session_layer import SessionLayer


def generate_sessions(total_sessions: int = 100):
    """Generate realistic sessions across 6 domains (100 or 250 in stress mode)."""
    sessions = []
    projects = ["ledger-engine", "auth-gateway", "mobile-app", "k8s-infra", "ml-pipeline", "data-warehouse"]

    # Defined milestones and needles
    milestones = {
        # Needles
        2: ("k8s-infra", "Database Vault Root Token", "Root database encryption key is sealed in Vault KMS under path secrets/kms/master_v1."),
        7: ("auth-gateway", "Internal OIDC Client Secret", "The internal identity provider client secret is oidc_sec_9941a82."),
        15: ("ledger-engine", "Rounding Precision Standard", "All monetary computations must use 6 decimal places rounded half-even (Bankers Rounding)."),
        23: ("mobile-app", "Biometric Keychain Service Name", "Keychain service name is registered as com.app.secure.biometrics."),
        31: ("ml-pipeline", "Embedding Dimension Config", "The vector embedding dimension is locked to 768 float32 values."),
        48: ("data-warehouse", "Iceberg S3 Warehouse Bucket", "Iceberg warehouse root directory is s3://dw-production-data-lake/iceberg/."),
        62: ("auth-gateway", "JWT Signing Algorithm", "JWT signing algorithm enforced as Ed25519; RS256 deprecated."),
        77: ("ledger-engine", "Idempotency Key Expiry TTL", "Transaction idempotency keys expire in Redis after exactly 86400 seconds."),
        85: ("k8s-infra", "VPC CIDR Subnet Block", "Primary production VPC CIDR allocation is 10.140.0.0/16."),
        93: ("ml-pipeline", "Inference Batch Latency SLO", "Model inference batch latency budget is strictly 25 milliseconds P99."),

        # Cascading Supersessions
        5: ("auth-gateway", "Initial Rate Limiting Tier", "Session rate limiting set to fixed window 60 requests per minute."),
        35: ("auth-gateway", "Update Rate Limiting Algorithm", "Replaced fixed window rate limiter with sliding token bucket 120 req/min. Supersedes Session 5.", {"supersedes": 5}),
        75: ("auth-gateway", "Distributed Rate Limiter Final", "Migrated rate limiter to Redis sliding log with 300 req/min burst capacity. Supersedes Session 35.", {"supersedes": 35}),

        10: ("ledger-engine", "Database Backend Engine", "Ledger engine uses PostgreSQL 15 with serializable isolation level."),
        50: ("ledger-engine", "Database Distributed Transition", "Migrated ledger storage from PostgreSQL to CockroachDB distributed SQL. Supersedes Session 10.", {"supersedes": 10}),

        12: ("mobile-app", "Local Storage Technology", "Offline cache implemented using SQLite via moor."),
        60: ("mobile-app", "Storage Engine Migration", "Migrated offline cache from SQLite to encrypted drift with SQLCipher. Supersedes Session 12.", {"supersedes": 12}),

        # Multi-Hop Pieces
        18: ("auth-gateway", "Cluster Hostname Auth", "Auth gateway internal hostname is auth-gw.corp.internal."),
        44: ("auth-gateway", "Cluster Port Auth", "Auth gateway listens on port 9443 for internal services."),
        82: ("auth-gateway", "Cluster Protocol Auth", "Auth gateway strictly enforces mTLS v1.3 with mutual cert verification."),

        25: ("data-warehouse", "ClickHouse Ingestion Host", "ClickHouse ingestion endpoint host is ch-ingest.analytics.local."),
        65: ("data-warehouse", "ClickHouse Native Port", "ClickHouse native protocol port configured to 9000."),

        # Temporal Sequence
        20: ("k8s-infra", "Incident 401 Step 1 Initial", "Incident 401 Timeline: Step 1 began when DNS resolver pods hit CPU throttling."),
        21: ("k8s-infra", "Incident 401 Step 2 Cascade", "Incident 401 Timeline: Step 2 occurred when downstream HTTP timeouts flooded fallback retry queues."),
        22: ("k8s-infra", "Incident 401 Step 3 Recovery", "Incident 401 Timeline: Step 3 completed after increasing CoreDNS replica count to 16."),

        # Extended Stress Milestones (for 250 sessions)
        120: ("ledger-engine", "Audit Log Retention Guarantee", "Immutable regulatory audit logs must be retained for 7 years in WORM S3 storage."),
        145: ("auth-gateway", "Adaptive Anomaly Detection", "Adaptive bot rate limiting threshold set to 15 suspicious patterns per IP per hour."),
        170: ("data-warehouse", "Delta Lake Parquet Compression", "Delta Lake table files are compressed using ZSTD level 3 algorithm."),
        195: ("ml-pipeline", "Model Quantization Runtime", "Production embedding model quantized to INT8 with ONNX Runtime acceleration."),
        225: ("k8s-infra", "Cross-Region Mesh Ingress Gateway", "Cross-region ingress mesh proxy routes via envoy-mesh.global.infra:443."),
    }

    for i in range(1, total_sessions + 1):
        if i in milestones:
            item = milestones[i]
            extra = item[3] if len(item) > 3 else {}
            sessions.append({
                "session": i,
                "project": item[0],
                "title": item[1],
                "text": item[2],
                "extra": extra,
                "epoch_days_ago": total_sessions - i
            })
        else:
            proj = projects[i % len(projects)]
            sessions.append({
                "session": i,
                "project": proj,
                "title": f"Routine Maintenance Task {i}",
                "text": f"Performed maintenance task {i} in {proj}. Verified configurations and ran standard automated unit tests.",
                "extra": {},
                "epoch_days_ago": total_sessions - i
            })
    return sessions


EVALUATION_QUERIES = [
    # --- Category 1: Temporal Needle Retrieval (10 Queries) ---
    {"cat": "1. Needle Depth", "proj": "k8s-infra", "q": "Vault root database encryption key path", "expect": ["secrets/kms/master_v1"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "auth-gateway", "q": "Internal identity provider client secret", "expect": ["oidc_sec_9941a82"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "ledger-engine", "q": "Monetary rounding precision rule", "expect": ["6 decimal places", "bankers rounding"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "mobile-app", "q": "Biometric keychain service registration name", "expect": ["com.app.secure.biometrics"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "ml-pipeline", "q": "Vector embedding dimension configuration size", "expect": ["768"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "data-warehouse", "q": "Iceberg S3 warehouse root bucket directory", "expect": ["s3://dw-production-data-lake/iceberg/"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "auth-gateway", "q": "JWT token signing algorithm standard", "expect": ["ed25519"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "ledger-engine", "q": "Transaction idempotency key expiry time TTL", "expect": ["86400"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "k8s-infra", "q": "Primary production VPC CIDR block", "expect": ["10.140.0.0/16"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "ml-pipeline", "q": "Model inference batch latency budget SLO", "expect": ["25 milliseconds"], "banned": []},
    {"cat": "1. Needle Depth", "proj": "ledger-engine", "q": "Immutable regulatory audit log retention period", "expect": ["7 years"], "banned": [], "min_sessions": 200},
    {"cat": "1. Needle Depth", "proj": "auth-gateway", "q": "Adaptive bot anomaly detection rate limit threshold", "expect": ["15 suspicious patterns"], "banned": [], "min_sessions": 200},
    {"cat": "1. Needle Depth", "proj": "data-warehouse", "q": "Delta Lake table compression codec", "expect": ["zstd level 3"], "banned": [], "min_sessions": 200},
    {"cat": "1. Needle Depth", "proj": "ml-pipeline", "q": "Production model quantization and runtime engine", "expect": ["int8", "onnx runtime"], "banned": [], "min_sessions": 200},
    {"cat": "1. Needle Depth", "proj": "k8s-infra", "q": "Cross-region ingress mesh proxy gateway address", "expect": ["envoy-mesh.global.infra:443"], "banned": [], "min_sessions": 200},

    # --- Category 2: Cascading Knowledge Supersession (10 Queries) ---
    {"cat": "2. Supersession", "proj": "auth-gateway", "q": "What is the active rate limiting configuration?", "expect": ["300 req/min", "redis sliding log"], "banned": ["60 requests per minute", "fixed window"]},
    {"cat": "2. Supersession", "proj": "auth-gateway", "q": "Rate limiter algorithm in production", "expect": ["redis sliding log"], "banned": ["fixed window 60"]},
    {"cat": "2. Supersession", "proj": "ledger-engine", "q": "What database backend engine does ledger use?", "expect": ["cockroachdb"], "banned": ["postgresql 15 with serializable"]},
    {"cat": "2. Supersession", "proj": "ledger-engine", "q": "Ledger storage distributed database", "expect": ["cockroachdb"], "banned": ["postgresql 15"]},
    {"cat": "2. Supersession", "proj": "mobile-app", "q": "What offline local storage technology is active?", "expect": ["sqlcipher", "drift"], "banned": ["sqlite via moor"]},
    {"cat": "2. Supersession", "proj": "mobile-app", "q": "Offline cache storage engine implementation", "expect": ["sqlcipher"], "banned": ["sqlite via moor"]},
    {"cat": "2. Supersession", "proj": "auth-gateway", "q": "Is fixed window 60 req/min rate limit still active?", "expect": ["supersedes", "sliding log"], "banned": []},
    {"cat": "2. Supersession", "proj": "ledger-engine", "q": "Has PostgreSQL 15 been superseded?", "expect": ["cockroachdb"], "banned": []},
    {"cat": "2. Supersession", "proj": "mobile-app", "q": "Drift SQLCipher migration history", "expect": ["sqlcipher"], "banned": []},
    {"cat": "2. Supersession", "proj": "auth-gateway", "q": "Current active burst capacity rate limit", "expect": ["300 req/min"], "banned": ["60 req/min"]},

    # --- Category 3: Multi-Session Multi-Hop Synthesis (10 Queries) ---
    {"cat": "3. Multi-Hop", "proj": "auth-gateway", "q": "What is the full endpoint hostname and port for auth gateway?", "expect": ["auth-gw.corp.internal", "9443"], "banned": []},
    {"cat": "3. Multi-Hop", "proj": "auth-gateway", "q": "Auth gateway protocol port and mutual verification", "expect": ["mtls v1.3", "9443"], "banned": []},
    {"cat": "3. Multi-Hop", "proj": "auth-gateway", "q": "Internal auth cluster hostname port and TLS spec", "expect": ["auth-gw.corp.internal", "9443", "mtls"], "banned": []},
    {"cat": "3. Multi-Hop", "proj": "data-warehouse", "q": "ClickHouse ingestion endpoint host and native port", "expect": ["ch-ingest.analytics.local", "9000"], "banned": []},
    {"cat": "3. Multi-Hop", "proj": "data-warehouse", "q": "What port does ch-ingest.analytics.local use?", "expect": ["9000"], "banned": []},
    {"cat": "3. Multi-Hop", "proj": "data-warehouse", "q": "ClickHouse analytics ingestion server details", "expect": ["ch-ingest.analytics.local", "9000"], "banned": []},
    {"cat": "3. Multi-Hop", "proj": "auth-gateway", "q": "Auth gateway mTLS port and host", "expect": ["auth-gw.corp.internal", "9443"], "banned": []},
    {"cat": "3. Multi-Hop", "proj": "k8s-infra", "q": "KMS root token in production VPC", "expect": ["secrets/kms/master_v1"], "banned": []},
    {"cat": "3. Multi-Hop", "proj": "ledger-engine", "q": "CockroachDB ledger monetary precision", "expect": ["6 decimal places"], "banned": []},
    {"cat": "3. Multi-Hop", "proj": "ml-pipeline", "q": "768 vector embedding latency SLO", "expect": ["25 milliseconds"], "banned": []},

    # --- Category 4: Distractor Resistance & Noise Immunity (10 Queries) ---
    {"cat": "4. Distractors", "proj": "k8s-infra", "q": "Root database encryption Vault KMS", "expect": ["secrets/kms/master_v1"], "banned": ["routine maintenance", "iceberg", "biometrics"]},
    {"cat": "4. Distractors", "proj": "auth-gateway", "q": "OIDC internal secret key credentials", "expect": ["oidc_sec_9941a82"], "banned": ["routine maintenance", "cockroachdb"]},
    {"cat": "4. Distractors", "proj": "ledger-engine", "q": "Bankers rounding monetary calculation", "expect": ["bankers rounding"], "banned": ["routine maintenance", "auth-gw"]},
    {"cat": "4. Distractors", "proj": "mobile-app", "q": "Biometrics keychain secure registration", "expect": ["com.app.secure.biometrics"], "banned": ["routine maintenance", "s3://"]},
    {"cat": "4. Distractors", "proj": "ml-pipeline", "q": "Float32 vector embedding dimension", "expect": ["768"], "banned": ["routine maintenance"]},
    {"cat": "4. Distractors", "proj": "data-warehouse", "q": "Production data lake S3 Iceberg catalog", "expect": ["dw-production-data-lake"], "banned": ["routine maintenance"]},
    {"cat": "4. Distractors", "proj": "auth-gateway", "q": "Ed25519 JWT signing enforcement", "expect": ["ed25519"], "banned": ["routine maintenance"]},
    {"cat": "4. Distractors", "proj": "ledger-engine", "q": "Redis transaction idempotency TTL", "expect": ["86400"], "banned": ["routine maintenance"]},
    {"cat": "4. Distractors", "proj": "k8s-infra", "q": "Production VPC 10.140 CIDR allocation", "expect": ["10.140.0.0/16"], "banned": ["routine maintenance"]},
    {"cat": "4. Distractors", "proj": "ml-pipeline", "q": "P99 25ms inference latency budget", "expect": ["25 milliseconds"], "banned": ["routine maintenance"]},

    # --- Category 5: Temporal Sequencing & Chronology (10 Queries) ---
    {"cat": "5. Chronology", "proj": "k8s-infra", "q": "Incident 401 Step 1 initial trigger", "expect": ["dns resolver", "cpu throttling"], "banned": []},
    {"cat": "5. Chronology", "proj": "k8s-infra", "q": "Incident 401 Step 2 downstream impact", "expect": ["downstream http timeouts", "retry queues"], "banned": []},
    {"cat": "5. Chronology", "proj": "k8s-infra", "q": "Incident 401 Step 3 resolution action", "expect": ["coredns replica count", "16"], "banned": []},
    {"cat": "5. Chronology", "proj": "k8s-infra", "q": "Incident 401 timeline sequence events", "expect": ["step 1", "step 2", "step 3"], "banned": []},
    {"cat": "5. Chronology", "proj": "auth-gateway", "q": "Rate limiting evolution sequence", "expect": ["sliding token bucket", "redis sliding log"], "banned": []},
    {"cat": "5. Chronology", "proj": "ledger-engine", "q": "Ledger database storage evolution", "expect": ["postgresql", "cockroachdb"], "banned": []},
    {"cat": "5. Chronology", "proj": "mobile-app", "q": "Mobile offline storage migration sequence", "expect": ["sqlite", "sqlcipher"], "banned": []},
    {"cat": "5. Chronology", "proj": "k8s-infra", "q": "What resolved Incident 401?", "expect": ["coredns replica count to 16"], "banned": []},
    {"cat": "5. Chronology", "proj": "k8s-infra", "q": "What was the initial cause of Incident 401?", "expect": ["dns resolver pods hit cpu throttling"], "banned": []},
    {"cat": "5. Chronology", "proj": "auth-gateway", "q": "Did sliding token bucket replace fixed window?", "expect": ["token bucket", "fixed window"], "banned": []},
]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def run_comprehensive_longmemeval(db_path: Path, total_sessions: int = 100):
    sessions = generate_sessions(total_sessions=total_sessions)
    now_ms = int(time.time() * 1000)

    # 1. Sequential ingestion
    session_layer = SessionLayer(db_path=db_path)
    id_map = {}
    records = []
    for s in sessions:
        rec = session_layer.record(
            text=s["text"],
            title=s["title"],
            project=s["project"],
            origin="user-confirmed"
        )
        oid = rec["id"]
        id_map[s["session"]] = oid
        records.append((s, oid))

    # 2. Batch update metadata
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        for s, oid in records:
            epoch = now_ms - (s["epoch_days_ago"] * 86400 * 1000)
            supersedes_json = "[]"
            if "supersedes" in s.get("extra", {}):
                target_sess = s["extra"]["supersedes"]
                target_oid = id_map.get(target_sess)
                if target_oid:
                    supersedes_json = json.dumps([str(target_oid)])
                    con.execute("UPDATE observations SET type = 'superseded', superseded_by = ? WHERE id = ?",
                                (str(oid), target_oid))
            con.execute(
                "UPDATE observations SET created_at_epoch = ?, supersedes_refs = ? WHERE id = ?",
                (epoch, supersedes_json, oid)
            )
        con.commit()
    finally:
        con.close()

    # 3. Evaluate queries across projects
    results = []
    latencies = []
    layers = {}

    eval_queries = [q for q in EVALUATION_QUERIES if q.get("min_sessions", 0) <= total_sessions]

    for item in eval_queries:
        proj = item["proj"]
        if proj not in layers:
            layers[proj] = SessionLayer(project=proj, db_path=db_path)
        sl = layers[proj]

        t0 = time.perf_counter()
        hits = sl.search(item["q"], limit=5)
        lat_ms = (time.perf_counter() - t0) * 1000
        latencies.append(lat_ms)

        combined_text = " ".join(h.text for h in hits)
        norm_combined = norm(combined_text)

        # Check expected phrases
        missing = [p for p in item["expect"] if norm(p) not in norm_combined]

        # Check top hit doesn't carry banned obsolete facts
        top_text = hits[0].text if hits else ""
        norm_top = norm(top_text)
        banned_hit = [p for p in item["banned"] if norm(p) in norm_top]

        # Calculate rank of first hit satisfying expected phrases
        first_rank = None
        for r_idx, h in enumerate(hits):
            h_norm = norm(h.text)
            if all(norm(p) in h_norm for p in item["expect"][:1]):
                first_rank = r_idx
                break

        passed = (len(missing) == 0 and len(banned_hit) == 0)
        results.append({
            "category": item["cat"],
            "query": item["q"],
            "project": proj,
            "hits_count": len(hits),
            "top_hit": hits[0].text[:75] if hits else "(no hits)",
            "passed": passed,
            "latency_ms": lat_ms,
            "missing": missing,
            "banned_hit": banned_hit,
            "rank": first_rank
        })

    return results, latencies


def main():
    parser = argparse.ArgumentParser(description="Comprehensive LongMemEval Benchmark")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    parser.add_argument("--stress", action="store_true", help="Run aggressive stress mode (250 sessions)")
    parser.add_argument("--sessions", type=int, default=100, help="Total sessions to simulate (default: 100)")
    args = parser.parse_args()

    sessions_count = 250 if args.stress else args.sessions
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / f"longmemeval_{sessions_count}.db"
        results, latencies = run_comprehensive_longmemeval(db_path, total_sessions=sessions_count)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    mean_lat = sum(latencies) / total
    sorted_lats = sorted(latencies)
    p95_lat = sorted_lats[int(0.95 * total)]
    p99_lat = sorted_lats[int(0.99 * total)]

    # Recall and MRR
    rec1 = sum(1 for r in results if r["rank"] is not None and r["rank"] < 1)
    rec3 = sum(1 for r in results if r["rank"] is not None and r["rank"] < 3)
    rec5 = sum(1 for r in results if r["rank"] is not None and r["rank"] < 5)
    mrr = sum((1.0 / (r["rank"] + 1)) for r in results if r["rank"] is not None) / total

    # Category breakdown
    cats = {}
    for r in results:
        c = r["category"]
        cats.setdefault(c, {"total": 0, "passed": 0})
        cats[c]["total"] += 1
        if r["passed"]:
            cats[c]["passed"] += 1

    if args.json:
        print(json.dumps({
            "total_sessions": sessions_count,
            "total_queries": total,
            "passed": passed,
            "accuracy": passed / total,
            "recall_at_1": rec1 / total,
            "recall_at_3": rec3 / total,
            "recall_at_5": rec5 / total,
            "mrr": mrr,
            "latency_ms": {"mean": mean_lat, "p95": p95_lat, "p99": p99_lat},
            "category_breakdown": cats,
            "results": results
        }, indent=2))
        sys.exit(0 if passed == total else 1)

    print(f"\n=== LongMemEval {sessions_count}-Session, {total}-Query Benchmark Results ===")
    for c, stats in cats.items():
        pct = stats["passed"] / stats["total"]
        print(f"  • {c:<38}: {stats['passed']:2d}/{stats['total']:2d} ({pct:.0%})")

    print(f"\nOverall Accuracy: {passed}/{total} = {passed/total:.0%}")
    print(f"Ranking Metrics:  Recall@1: {rec1/total:.1%} | Recall@3: {rec3/total:.1%} | Recall@5: {rec5/total:.1%} | MRR: {mrr:.3f}")
    print(f"Latency Profile:  Mean: {mean_lat:.2f}ms | P95: {p95_lat:.2f}ms | P99: {p99_lat:.2f}ms")
    print(f"Token Spend:      0 tokens (100% on-device SQLite FTS5)")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
