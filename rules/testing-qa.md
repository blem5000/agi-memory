# Testing & Quality Assurance

All verification runs 100% offline without API keys, network access, or external daemons.

## Writing a New Test File

Every test entry point imports `_isolate` before anything from `agi_memory`:

```python
import _isolate  # noqa: F401,E402  -- must run before agi_memory resolves any path
```

It points the whole process at a throwaway `AGI_MEMORY_DIR`, clears every
`*_DB` / `*_VAULT` / `*_GRAPH_DB` / `*_STATE` override that outranks it, and turns
background auto-sync off. Tests written without it put fixture memories into the
developer's real store, and auto-sync pushed them to the developer's git remote.
Isolating inside a test block is too late, because `agi_memory.config` fixes
paths at import. Isolating only `AGI_MEMORY_DB` also isn't enough, because the
vault does not follow it.

Open SQLite connections in a `finally`, and keep any delete-then-reinsert inside
one transaction. Windows CI fails on a leaked handle, and a process that exits
mid-rebuild must leave the previous rows, not an empty table.

## Required Verification Checklist

Before committing or pushing any code changes, all 8 test suites must pass:

1. **Unit & Offline Integration Tests**:
   ```bash
   python3 tests/test_offline.py
   ```
   Verifies layers, base classes, SQLite schema bootstrap, ranking preservation, vault export/import, deduplication/compaction, local Git sync, cold-start bootstrap, observation inspection, soft/hard deletion, and developer observability CLI.

2. **L1 Retrieval Evaluation**:
   ```bash
   python3 tests/eval_l1.py
   ```
   Evaluates L1 Working Memory accuracy (10/10 target) and query latency (<5ms).

3. **L2 Knowledge Graph Evaluation**:
   ```bash
   python3 tests/eval_l2.py
   ```
   Evaluates L2 multi-hop graph traversal accuracy (6/6 target) and latency (<1ms).

4. **L3 Episodic History Evaluation**:
   ```bash
   python3 tests/eval_l3.py
   ```
   Evaluates L3 session-history recall (10/10 target) and latency (<1ms). Seeds a
   multi-project session history, then checks term-level recall, project-scoped
   timelines, and that the recap names the most recent session.

5. **L4 Structural Code Graph Evaluation**:
   ```bash
   python3 tests/eval_l4.py
   python3 tests/eval_usage.py
   ```
   Evaluates L4 graph accuracy (25/25 target) and latency (<1ms) against a fixture
   repository whose call edges are true by construction, covering Python,
   TypeScript and Go: callers, dependencies, blast radius, and structure.

6. **MCP Handshake & Tool Protocol**:
   ```bash
   agi-integrate test
   ```
   Verifies JSON-RPC 2.0 stdio communication, `initialize`, `ping`, and registration of all 16 tools:
   - `memory_recall`
   - `memory_recall_deep`
   - `memory_record`
   - `memory_promote`
   - `memory_sync`
   - `memory_pin`
   - `memory_unpin`
   - `memory_blocks`
   - `memory_bootstrap`
   - `memory_timeline`
   - `memory_session_outcome`
   - `code_structure`
   - `code_callers`
   - `code_dependencies`
   - `code_impact`
   - `code_index`

7. **Two-Machine Sync**:
   ```bash
   python3 tests/multi_machine_test.py
   ```
   Drives two isolated machines through record and sync against a shared
   remote, asserting both converge and a third machine cloning fresh sees
   everything. Verified to fail (4/11) without the union merge policy.

8. **Comprehensive 12-Tier Production Stress Test**:
   ```bash
   python3 tests/stress_test.py
   ```
   Evaluates full production performance against real multi-thousand observation datasets:
   - L1 Working Memory latency (<8ms p50, <16ms p95 on 14k observations)
   - L2 Recursive CTE traversal (<0.5ms)
   - Pure-SQL entity alias resolution (>4M lookups/sec, ~0.24 µs)
   - Core Memory block retrieval (<0.6ms)
   - Multi-agent concurrency throughput (>500 QPS across 100 concurrent workers)
   - In-flight conflict steering & temporal supersedence
   - Lifecycle hook latency (<35ms)
   - Vault compaction throughput (>5,000 records/sec)
   - Episodic session lifecycle & timeline retrieval (<0.5ms)
   - Structural code graph AST indexing & recursive impact analysis
   - RSS memory footprint (0 MB idle background RAM, 0 background daemons)
