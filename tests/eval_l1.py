"""L1 stress test: 10 technical questions graded by the RANK of the record
that carries the answer + latency. Local retrieval only — zero LLM calls.
Runs on an isolated evaluation DB.

Grading is per-hit, not a concatenated blob: a question counts at cutoff k
only if every required phrase appears by rank k, so an answer sitting in
slot 5 shows up as Recall@5 10/10 but Recall@1 lower -- which is the
difference between "the store has it" and "the caller sees it first".
The 10-question corpus measures this corpus, so the numbers are regression
baselines, not quality claims about arbitrary stores.
"""
import _isolate  # noqa: F401,E402  -- must run before agi_memory resolves any path
import argparse
import json
import re
import tempfile
import time
import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.layers.session_layer import SessionLayer

SAMPLE_DATA = [
    ("mobile-app", "Haptics Architecture", "Decided to use two tiny free functions (hapticTap, hapticToggle) rather than a service provider or singleton."),
    ("mobile-app", "Code Format Discipline", "Rule: code formatting must target only explicitly changed files; bare repo format once rewrote 66 untouched files."),
    ("mobile-app", "Format Incident Root Cause", "What went wrong with bare format: bare formatter formatted 66 untouched files across the repository."),
    ("mobile-app", "Touch Handling Primitives", "TapArea is for custom widgets only; primitive and platform components receive only a haptic callback."),
    ("mobile-app", "Audit Baseline Pattern", "Pinned audit agents to last commit; fix by refreshing baselines after landing work."),
    ("tax-processor", "Tax Engine Scope", "Phase 1 scope is personal income tax filing; corporate accounting deferred."),
    ("tax-processor", "Document Intake Screen", "Form 16 must not be a separate screen; all documents upload to a single documents screen with OCR."),
    ("tax-processor", "Ledger Role", "Tax engine becomes the book of record (ledger), not a feeder into external systems."),
    ("tax-processor", "Accepted File Types", "Intake accepts json, xlsx, and pdf files."),
    ("tax-processor", "Phase 1 Artifact", "Phase-1 primary artifact is computation of income feeding tax schedules, not a double-entry ledger."),
]

QUESTIONS = [
    ("mobile-app", "What was decided about haptics, service or functions?", ["haptictap", "haptictoggle"]),
    ("mobile-app", "What is the rule about code format?", ["explicitly changed files"]),
    ("mobile-app", "What went wrong with the bare format run?", ["66 untouched files"]),
    ("mobile-app", "TapArea for custom widgets, what about primitives?", ["haptic callback"]),
    ("mobile-app", "What is the audit baseline pattern?", ["pinned", "last commit"]),
    ("tax-processor", "What is the phase 1 scope?", ["personal income tax"]),
    ("tax-processor", "Should Form 16 be a separate screen?", ["single documents screen"]),
    ("tax-processor", "Is the system the ledger or a feeder?", ["book of record"]),
    ("tax-processor", "What intake file types are accepted?", ["json", "xlsx", "pdf"]),
    ("tax-processor", "Ledger vs computation: what is the phase-1 artifact?", ["computation of income"]),
]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def rank_of(hits, phrases):
    """Deepest rank (0-based) any required phrase first appears at.

    None when a phrase is in no hit: the question misses entirely and stays
    out of every cutoff. Each phrase may land in a different hit -- what is
    graded is how deep the caller must read, not whether the phrases sat in
    one record.
    """
    deepest = 0
    for p in phrases:
        want = norm(p)
        idx = next((i for i, h in enumerate(hits) if want in norm(h.text)), None)
        if idx is None:
            return None
        deepest = max(deepest, idx)
    return deepest


def main():
    parser = argparse.ArgumentParser(description="Evaluate L1 Working Memory retrieval accuracy and latency.")
    parser.add_argument("--db", help="Path to SQLite database (defaults to isolated test DB)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp_dir:
        eval_db = Path(args.db) if args.db else Path(tmp_dir) / "eval_l1.db"
        cm_seed = SessionLayer(worker="http://127.0.0.1:99999", db_path=eval_db)
        for proj, title, text in SAMPLE_DATA:
            cm_seed.record(text=text, title=title, project=proj)

        layers = {}
        rows = []
        for proj, q, exp in QUESTIONS:
            layers.setdefault(proj, SessionLayer(worker="http://127.0.0.1:99999", project=proj, db_path=eval_db))
            t = time.perf_counter()
            hits = layers[proj].search(q, limit=5)
            lat = round(time.perf_counter() - t, 4)
            rank = rank_of(hits, exp)
            rows.append({"q": q, "rank": rank, "lat": lat})
            status = "PASS" if rank is not None else "FAIL"
            print(f"{status} {lat*1000:6.2f}ms :: {q[:60]}", flush=True)

        found = [r["rank"] for r in rows if r["rank"] is not None]
        acc = len(found) / len(rows)
        mean_ms = (sum(r["lat"] for r in rows) / len(rows)) * 1000
        print(f"\nL1 Score: {len(found)}/{len(rows)} = {acc:.0%}, mean latency: {mean_ms:.2f}ms")
        rec = {k: sum(1 for r in found if r < k) for k in (1, 3, 5)}
        mrr = sum(1.0 / (r + 1) for r in found) / len(rows)
        print(f"Rank: Recall@1 {rec[1]}/{len(rows)}, @3 {rec[3]}/{len(rows)}, "
              f"@5 {rec[5]}/{len(rows)}, MRR {mrr:.3f}")


if __name__ == "__main__":
    main()
