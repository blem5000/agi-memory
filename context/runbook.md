# Operational Runbook

## Daily Operations

### 0. First-Time Remote Setup
The vault commits locally from the first write, but nothing leaves the machine
until a remote exists — `agi-memory sync status` reports `no_remote` until then.
```bash
# Create a private GitHub repo via the gh CLI and push the vault to it
agi-memory sync init --create-private [--repo-name agent-memory-vault]

# Or point at a remote you already have
agi-memory sync init https://github.com/<you>/<repo>.git

# Confirm
agi-memory sync status
```
Before the first push on a long-lived vault, run `git -C ~/.agent-memory/vault
gc`. Each sync commits a fresh copy of `observations.jsonl`, so the loose
objects accumulate badly — one real vault packed from 746 MB to 25 MB.

### 1. Synchronizing Across Machines
When switching from Laptop to Desktop:
```bash
# Pull remote memories and reconcile local SQLite cache
agi-sync now
# or: python3 -m agi_memory.sync now
```
Auto-sync already does this: every `record` and `add_edge` schedules a
3s-debounced background sync, and the `session-end` hook forces one. Run it by
hand when you want the push to have happened *before* you walk away.

### 2. Manual Compaction & Deduplication
If large volumes of memories have been recorded:
```bash
# Deduplicate observations and graph edges, then re-index SQLite
agi-sync dedupe
# or: python3 -m agi_memory.sync dedupe
```

### 3. Promoting Working Memory to Knowledge Graph
Curate high-signal items from L1 observations into L2 triples:
```bash
# Dry run to inspect candidates
python3 -m agi_memory.promote --dry-run --project agi-memory

# Ingest top 20 durable learnings
python3 -m agi_memory.promote --project agi-memory --limit 20
```

### 4. Wire or Refresh Coding Assistants
Inspect or install MCP connections across tools:
```bash
# Check all detected tools
agi-integrate status
# or: python3 -m agi_memory.integrate status

# Reconfigure all installed tools
agi-integrate install all
```

### 5. Resolving Conflicting Decisions
When an AI assistant receives a `[Notice - Potential Overlap Found]` message during `memory_record`:
- If the new pattern overrides the older one, the assistant immediately re-invokes `memory_record` specifying `supersedes="#<id>"`.
- You can also manually supersede an observation from the CLI:
```bash
python3 -c "from agi_memory.layers.session_layer import SessionLayer; SessionLayer(project='my-app').record(text='New decision', supersedes='#1234')"
```

### 6. Querying Superseded vs Active Rules
By default, active rules are ranked ahead of superseded rules:
```bash
# Active search
agi-recall "storage" --project agi-memory
# or: python3 -m agi_memory.recall "storage" --project agi-memory

# Deep search including L2 knowledge graph
agi-recall "storage" --project agi-memory --deep
```

### 7. Running Production Stress Tests & Benchmarks
To evaluate system performance, latency distributions, and throughput:
```bash
# Execute the authentic 12-tier benchmark suite
python3 tests/stress_test.py
```

### 8. Managing Automated Lifecycle Hooks
To wire or refresh lifecycle hooks (`session-start`, `pre-compact`, `session-end`, `pre-commit`, `post-commit`):
```bash
# Install hooks for all detected tools
agi-integrate hooks all

# Target specific tool (e.g. Claude Code, OpenCode, or Antigravity)
agi-integrate hooks claude opencode agy git

# Target project scope
agi-integrate hooks all --scope project
```

### 9. Core Memory Pinning & Invariants
Pin critical rules so they are unconditionally injected on session startup and recall:
```bash
agi-memory pin zero_pip_deps "Zero external pip dependencies: strictly Python stdlib and sqlite3" \
  --category architecture --project agi-memory
agi-memory blocks
agi-memory unpin zero_pip_deps

# Or via MCP tools: memory_pin / memory_unpin / memory_blocks
```

### 9b. Curating the Entity Alias Table
Aliases resolve a term to its canonical form at write and query time, so `k8s`
and `Kubernetes` reach the same memories. The table ships with 14 seed entries
and learns nothing on its own — what is not in it does not resolve.
```bash
agi-memory alias list
agi-memory alias add k8s Kubernetes --category infra
agi-memory alias rm k8s      # a wrong entry rewrites every term it matches
```

### 9c. Marking How a Session Ended
An unmarked session is recorded as `unknown` and the next session is told not to
resume it. Marking it is what turns that noise into a signal.
```bash
agi-memory outcome completed    # or abandoned | blocked | superseded
```

### 10. Cold-Start Seeding on New Repositories
When connecting agi-memory to a newly attached project or workspace:
```bash
# Seed initial architecture, git commit rationale, and structural code graph
agi-memory bootstrap --repo .

# Or via agi-integrate
agi-integrate bootstrap /path/to/project --max-commits 25
```

### 11. Developer Observability & Memory Curation
Audit and curate stored memories from the command line:
```bash
# View recent memories in a table
agi-memory log -n 20 --project agi-memory

# Inspect observation details, facts, narrative, and concepts
agi-memory inspect 101

# Delete or supersede an observation
agi-memory delete 101
agi-memory delete 101 --hard

# Manage pinned core invariants
agi-memory pin "zero_pip_deps" "Zero external pip dependencies" --category architecture
agi-memory blocks
agi-memory unpin "zero_pip_deps"
```

### 12. Structural Code Graph & Impact Analysis
Inspect symbol structure, callers, and blast radius directly:
```bash
# Outline symbols in file or directory
agi-memory structure src/

# Find inbound callers of a function or class
agi-memory callers SessionLayer

# Find outbound dependencies of a symbol
agi-memory dependencies recall

# Analyze blast-radius impact before refactoring
agi-memory impact SessionLayer

# Incrementally index directory into code graph
agi-memory index src/
```

### 13. Episodic Session History & Timeline
Inspect what coding assistants accomplished in recent sessions:
```bash
# View recent session timeline and summaries
agi-memory timeline -n 10 --project agi-memory
```

## Initializing a Project

```bash
cd your-project
agi-integrate init .          # wires .mcp.json, per-tool adapters, hooks,
                              # and the /agi-init slash command (9 formats)
agi-memory analyze            # optional: see the detected stack and commands
```

Then run `/agi-init` inside your assistant. It reads the codebase and writes
`rules/architecture.md`, `rules/testing-qa.md`, `context/data-model.md`,
`context/runbook.md`, and the `AGENTS.md` / `CLAUDE.md` index from what it finds.

Use `agi-integrate init . --force` to overwrite existing files, and
`--scope user` to install the slash command globally instead of per-project.
