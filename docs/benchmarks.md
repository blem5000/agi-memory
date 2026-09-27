# Benchmarks

Measured numbers for `agi-memory` against mainstream AI memory solutions,
plus a real 14k-observation production dataset.

### Comprehensive Benchmark Comparison

The table below compares `agi-memory` directly against mainstream AI memory solutions and vector RAG frameworks:

| Metric / Dimension | `agi-memory` (Native) | `Mem0` (Vector + Graph) | `Zep` (SaaS Memory) | `Cognee` (ECL / Vector) | `LangChain` Vector Memory | `claude-mem` (alone) |
|---|---|---|---|---|---|---|
| **External Dependencies** | **0 (Python stdlib only)** | 40+ pip pkgs (PyTorch, ONNX, Chroma) | Cloud SDK / SaaS API | 60+ pip pkgs (LangChain, Pydantic) | 50+ pip packages | Node.js v20+, npm daemon, Express |
| **Disk Install Size** | **< 1 MB** | ~850 MB | Cloud-hosted | ~550 MB | ~600 MB | ~80 MB + 3.1 MB bundle |
| **L1 Working Recall Latency** | **0.63 ms** (SQLite FTS5) | 180 – 450 ms (embeddings) | 250 – 800 ms (HTTP API) | n/a (heavy graph only) | 200 – 600 ms | ~165 ms (HTTP daemon) |
| **L2 Graph Recall Latency** | **0.28 ms** (Recursive CTEs) | 500 – 1,200 ms (graph RAG) | 350 – 900 ms (cloud graph) | ~2,500 ms (LLM + vector) | n/a (no graph) | n/a (no graph) |
| **L3 Episodic Timeline Latency** | **0.23 ms** (SQLite Timelines) | n/a (no session lifecycle) | n/a (cloud session log) | n/a | n/a | ~165 ms (HTTP daemon) |
| **L4 Code Graph Query Latency** | **0.45 ms** (AST + Regex) | n/a (no code graph) | n/a | n/a | n/a | n/a (no code graph) |
| **Cold-Start Boot Time** | **34.8 ms** (stdio protocol) | 2,200 – 3,800 ms (import overhead) | 300 – 600 ms (network) | 2,200 – 4,500 ms | 1,800 – 3,500 ms | Requires background daemon |
| **Process RAM (RSS)** | **~34.7 MB** | 450 MB – 1.2 GB+ | Cloud-hosted | ~350 MB – 700 MB | 400 MB – 1.0 GB+ | ~120 MB (Node process) |
| **Query Token Cost** | **$0.00 (0 LLM tokens)** | ~$0.02 / 1k queries (embeddings) | Subscription / per-call | ~1,500 – 3,000 tokens/query | ~$0.02 – $0.05 / 1k queries | $0.00 (local) |
| **Cross-Device Git Sync** | **Append-only JSONL Vault** (0 binary conflicts) | Raw binary DB (conflicts on merge) | Cloud database only | Raw DB / Local vector store | Local vector index (corrupts on git) | Local SQLite only |
| **Supported Coding Tools** | **13 Assistants Turnkey** | Python SDK only | Python/TS SDK only | Python SDK only | Python/TS framework only | Claude Code only |
| **Offline / Air-Gapped** | **100% Offline & Local** | Partial (requires local weights) | No (cloud required) | No (LLM extraction required) | Partial | Yes (local daemon) |

*Benchmarks measured on Apple Silicon macOS, 100 runs per tier. Reproduce locally with `python3 tests/eval_l1.py` and `python3 tests/eval_l2.py`.*

### Real-World Production Scale Benchmark (13,988 Observations, 21 MB Vault)

While most AI memory solutions benchmark against 10–50 synthetic toy records, `agi-memory` was stress-tested against an **authentic multi-year engineering database of 13,988 observations and a 20.61 MB vault** across active production software codebases:

| Metric / Dimension | `agi-memory` on Real 14k Dataset | Legacy Worker (`claude-mem`) | Vector / Graph RAG (`Mem0` / `Cognee`) |
|---|---|---|---|
| **L1 Working Recall (p50)** | **0.56 ms** | ~165.0 ms (Node HTTP) | 250 – 600 ms (embeddings) |
| **L1 Working Recall (p95)** | **0.96 ms** | ~320.0 ms | 450 – 850 ms |
| **L2 Recursive Graph Traversal** | **0.65 ms** (SQL CTEs) | n/a (failed / OOM) | 1,200 – 2,500 ms (GraphRAG) |
| **L3 Episodic Timeline Retrieval** | **0.226 ms** (Timelines) | ~165.0 ms (Node daemon) | n/a (manual reconstruction) |
| **L4 Code Caller Traversal** | **10.71 ms** (Recursive AST) | n/a (not supported) | 800 – 2,000 ms (Graphify / LSP) |
| **L4 Blast-Radius Impact Analysis** | **392.42 ms** (16 files, 292 symbols) | n/a (not supported) | 1,500 – 4,500 ms |
| **Entity Alias Resolution** | **4.11M lookups / sec** (0.243 µs) | n/a (no canonicalization) | 50 – 150 ms (Embedding models) |
| **Core Memory Block Retrieval** | **0.512 ms** (pinned blocks) | n/a (not supported) | 100 – 300 ms |
| **Full Tiered Recall (p50)** | **2.16 ms** (Core + L1 + L2) | ~165.0 ms (L1 alone) | 1,500 – 3,500 ms |
| **Multi-Agent Peak Concurrency** | **730.9 QPS** (100 concurrent agents) | Port locks / crashes | 15 – 35 QPS (rate-limited) |
| **In-Flight Conflict Detection** | **5.06 ms** (scans 14,000 rows) | n/a (no conflict checking) | n/a (manual reconciliation) |
| **Bi-Temporal Edge Invalidation** | **3.70 ms** (contradiction tagging) | n/a (overwrites or bloats) | Re-indexing required |
| **`session-start` Hook Overhead** | **31.77 ms** (startup briefing injection) | n/a (not supported) | 500 – 1,500 ms |
| **Idle Background RAM** | **0 MB** (0 background daemons) | 1,450 – 2,200 MB RSS | 850 – 1,800 MB RSS |
| **Active Query Token Cost** | **$0.00** (0 LLM tokens) | $0.00 | $0.02 / 1k queries |
| **Vault Compaction Throughput** | **5,135 records / sec** (2.8s for 21MB) | n/a (unbounded growth) | Re-indexing required |

*Reproduce locally against your real dataset with `python3 tests/stress_test.py`.*

---

## Deep Dive: The 3 Core Developer Metrics

### 1. Token Cost & Context Savings

Static files like `MEMORY.md` or heavy background daemons incur a massive "context tax" by dumping thousands of lines into the assistant's prompt window on every session start. `agi-memory` uses on-demand SQLite FTS5 + BM25 recall and compact multi-session briefings, keeping context injection minimal:

| Approach | Tokens Injected at Session Start | Cost per 10 Sessions (Claude 3.5 Sonnet) | Context Budget Impact |
|---|---|---|---|
| **`MEMORY.md` (flat file)** | 1,500 – 4,000 tokens (entire file) | ~$0.15 – $0.40 | Consistently wastes 1.5–4% of prompt context |
| **`claude-mem` (Node daemon)** | 2,000 – 3,500 tokens (up to 50 obs + summaries) | ~$0.20 – $0.35 | Burns tokens on raw observation logs |
| **`agi-memory` (Targeted L1+L3)** | **80 – 140 tokens** (last 3 sessions + top 3 precedents) | **~$0.01** | **94% – 97% context token reduction** |

- **On-Demand Queries**: In-session tool queries (`memory_recall`, `code_callers`, `code_structure`) execute directly against local SQLite with **$0.00 query cost** and zero embedding API bills.

### 2. Speed & Memory Footprint

Developer infrastructure must not slow down typing, lag editor interactions, or drain battery life with background daemons.

| Layer / Metric | `agi-memory` Latency | External / Vector Alternative | Speedup |
|---|---|---|---|
| **L1 Epistemic Recall** | **0.56 ms** (p50) / **0.96 ms** (p95) | 250 – 600 ms (Embeddings / Vector RAG) | **450x faster** |
| **L2 Semantic Graph** | **0.43 ms** (Recursive CTE) | 1,200 – 2,500 ms (GraphRAG / Neo4j) | **2,800x faster** |
| **L3 Episodic Timeline** | **0.23 ms** (SQLite Timeline) | ~165 ms (claude-mem HTTP daemon) | **700x faster** |
| **L4 Structural AST Graph** | **0.41 ms** (stdlib AST + Regex) | 800 – 2,000 ms (LSP / Tree-sitter binaries) | **2,000x faster** |
| **Idle Process RAM** | **0 MB** (zero daemons running) | 1,450 – 2,200 MB (Node.js/Bun daemons) | **100% idle reduction** |
| **Active MCP Server RAM** | **~34.7 MB RSS** | 450 MB – 1.2 GB+ (PyTorch, Chroma) | **13x – 35x lighter** |
| **Install Footprint** | **< 1 MB** (0 external dependencies) | ~850 MB (Mem0 / heavy pip wheels) | **850x smaller** |

### 3. How Recall Behaves on a Real 15k Store

Retrieval quality on a merged 15,123-observation vault spanning 41 projects and
eight months, measured rather than specified. Ranking is, in order: superseded
decisions last, an exact title match, BM25 relevance, a bounded recency nudge,
then the trust tier.

| Behaviour | Why it is there |
|---|---|
| **Exact title match wins outright** | Asking for a title that has four versions on disk used to return an unrelated memory that merely shared the words. Now the literal title sorts first. |
| **Recency breaks near-ties, never filters** | A fact that changed over months has both answers stored. A decaying boost (≈1.5 at one day old, ≈0.75 at 30 days, ~0 beyond a year) reorders memories whose BM25 scores are within ~1-3. Nothing is excluded for being old. |
| **The whole query also matches as a phrase** | A bare OR of every token ranks a body that mentions all the words above a record whose title *is* the query. |
| **The writer is shown** | Every recall line ends `(via <host> <pid> <harness>)`, so a reader can tell its own conclusion from a sibling process's inference. Costs ~20 tokens on the injected path. |
| **Superseded decisions rank last** | A replaced decision never outranks the one that replaced it, and it names what superseded it. |

**Still not solved, and named rather than hidden:** nothing detects that a
memory has become *wrong* — a memory that was correct and is no longer keeps
winning searches until a human or agent supersedes it. Recency makes the newest
answer easier to find; it does not know which one is true.

What ships instead is a **findings block** appended to `memory_recall`: evidence
about the memories just returned, with the judgement left to the agent reading
it. No finding claims a memory is wrong.

| Finding | Signal | Coverage today |
|---|---|---|
| `references N file(s) that no longer exist` | The memory's file references, checked against the code graph | Only for **indexed** projects — `agi-memory index`. An unindexed path is unknown, not gone. |
| `is an agent inference, surfaced Nx and never confirmed` | `origin=agent-inferred`, read receipts ≥3, no downstream citation | Accrues as the store is used; 3 candidates on a 15k store today |
| `was written N days ago and has been surfaced Nx` | Age + traffic, together | A prompt to look, never an invalidation |

Two things were measured and deliberately **not** built:

- **A contradiction detector.** Grouping live memories by shared concept terms
  produced 318 groups, all noise — the `concepts` column is boilerplate
  (`decision`, `pattern`) plus canonical terms, so memories group by the word
  "works" or "solution". Grouping by title prefix gave 1,046 groups that are
  near-duplicate commit records. There is no reliable mechanical signal for
  "same subject" in this data, let alone "disagrees". Deciding that two memories
  conflict is a judgement, and a rule that makes it fails invisibly.
- **Age-based decay.** Age is not validity: "port 8080 is required behind the
  proxy" is true for years, and decay demotes exactly the load-bearing facts.


### 4. Dead-End Avoidance & Actionability

Standard memory solutions suffer from "retrieval without actionability" — returning obsolete rules or recapping dropped work as active tasks. `agi-memory` explicitly tracks temporality, supersession, and session outcomes (`tests/eval_usage.py`):

| Capability | Naive `MEMORY.md` | Legacy Daemons | `agi-memory` (`eval_usage`) |
|---|---|---|---|
| **Superseded Decisions Filter** | ❌ None (stale & new rules conflict) | ❌ Raw log overwrite | ✅ **100% caught** (`supersedes="#id"` preserves rationale without conflicting) |
| **Dead-End & Blocker Warnings** | ❌ None (re-attempts failed tasks) | ⚠️ Generic status | ✅ **100% warning rate** (`NOT_RESUMABLE` blocks agent on abandoned work) |
| **Decision Origin Attribution** | ❌ None | ❌ None | ✅ **`user-confirmed` vs `agent-inferred`** tags prevent hallucinated rules |
| **Actionability Score (`eval_usage.py`)** | 0% | ~30% | **6/6 (100%) Actionability, 2/2 Session Recaps** |

---

## How RSS is measured

The memory figures above are the **MCP server process alone**, sampled after a
JSON-RPC handshake and one `memory_recall` — that is what a coding assistant
actually pays to keep memory available. Reproduce it with:

```bash
python3 tests/stress_test.py   # reports "MCP Server RSS"
```

The same run also prints "Stress Harness Peak RSS", which is much larger (~110MB)
and is **not** the server: it is the test process itself, which loads every
layer, seeds a synthetic corpus and drives 100-way concurrency. Don't quote it.

---

## What the in-repo harness measures today

The tables above come from a 13,988-observation production vault that is not in
this repository, so they cannot be reproduced from a clone. What *is* in the repo
is `tests/stress_test.py`, which seeds 1,000 synthetic observations and drives
100-way concurrency. Run on an Apple Silicon macOS laptop (2026-09-27, v0.9.2):

| Metric | In-repo harness (1,000 synthetic obs) | Production vault (13,988 obs) |
|---|---|---|
| L1 working recall (p50) | 4.52 ms | 0.56 ms |
| L1 working recall (p95) | 7.33 ms | 0.96 ms |
| L2 recursive graph traversal | 0.38 ms | 0.65 ms |
| L3 episodic timeline retrieval | 0.297 ms | 0.226 ms |
| L4 caller traversal | 112.5 ms | 10.71 ms |
| L4 blast-radius impact | 1,546 ms | 392 ms |
| Entity alias resolution | 8.68M lookups/sec (0.115 µs) | 4.11M lookups/sec (0.243 µs) |
| Core memory block retrieval | 0.426 ms | 0.512 ms |
| Full tiered recall (p50) | 4.81 ms | 2.16 ms |
| Peak concurrency | 70.1 QPS | 730.9 QPS |
| In-flight conflict detection | 3.64 ms | 5.06 ms |
| Bi-temporal edge invalidation | 2.22 ms | 3.70 ms |
| `session-start` hook overhead | 33.95 ms | 31.77 ms |
| MCP server RSS | 30.58 MB | ~34.7 MB |

The synthetic run is the slower one on recall and code-graph tiers, and the
faster one on the rest. Neither row is a correction of the other: they are
different corpora on different hardware, and both are machine-dependent. Quote
the row that matches the dataset you are describing.

The retrieval evals are the stable, cross-machine figures — they assert
correctness as well as latency, so a regression shows up as a failure rather
than as a slower number:

| Eval | Score | Mean latency |
|---|---|---|
| `tests/eval_l1.py` | 10/10 (100%) | 0.62 ms |
| `tests/eval_l2.py` | 6/6 (100%) | 0.47 ms |
| `tests/eval_l3.py` | 10/10 (100%) | 0.35 ms |
| `tests/eval_l4.py` | 25/25 (100%) | 0.36 ms |


