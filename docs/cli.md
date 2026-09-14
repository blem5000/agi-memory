# CLI Usage

### Developer Observability & Curation CLI
Audit, inspect, and curate memories and codebase graphs directly from the terminal:
```bash
# List recent observations in a clean tabular view
agi-memory log -n 20 --project my-app

# Inspect detailed facts, concepts, and full narrative of an observation
agi-memory inspect 101

# Soft-delete (mark superseded) or permanently purge an observation
agi-memory delete 101
agi-memory delete 101 --hard

# Inspect episodic session timeline
agi-memory timeline -n 10 --project my-app

# Structural code graph queries
agi-memory structure src/ --project my-app
agi-memory callers SessionLayer --project my-app
agi-memory dependencies recall --project my-app
agi-memory impact SessionLayer --project my-app
agi-memory index src/ --project my-app

# Bootstrap initial memories on a new repo from Git history, README & code symbols
agi-memory bootstrap --repo .

# Query working & durable memory directly
agi-memory recall "state management architecture" --deep

# Manage pinned core memory invariants
agi-memory pin "zero_pip_deps" "Zero external pip dependencies" --category architecture
agi-memory blocks
agi-memory unpin "zero_pip_deps"

# Curate the entity alias table, so a term and its canonical form reach the same
# memories. It ships with 14 seed entries and learns nothing on its own -- what
# is not in it does not resolve.
agi-memory alias list
agi-memory alias add k8s Kubernetes --category infra
agi-memory alias rm k8s
```

### Curating Knowledge (L1 -> L2 Knowledge Graph)
```bash
# Preview durable candidates (zero tokens)
python3 -m agi_memory.promote --dry-run --project my-app

# Ingest high-signal learnings into the native knowledge graph
python3 -m agi_memory.promote --project my-app --limit 20
```

---
