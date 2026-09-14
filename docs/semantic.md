# Hybrid Semantic Recall (optional)

Lexical FTS5/BM25 search misses paraphrases: a memory recorded as
*"authentication flow"* is invisible to a later query for *"login problem"*.
Hybrid recall adds an optional vector sidecar and fuses both rankings with
**Reciprocal Rank Fusion (RRF, k=60)**, following the
[Semble](https://github.com/MinishLab/semble) recipe:

```
lexical rank (FTS5/BM25) --\
                             +-- RRF --> fused ranking
semantic rank (cosine) ------/
```

Static [Potion](https://huggingface.co/collections/minishlab/potion)
embeddings (`minishlab/potion-code-16M-v2`, 16M params, 256 dims) have no
transformer forward pass at query time: milliseconds on CPU, tens of MB on
disk — no GPU, no 500MB ML stack. Symbol-like queries (`get_default_db`,
`Foo::bar`) automatically get 2x lexical weight, as in Semble.

## Core stays zero-dependency

`model2vec`/`numpy` live in the **`semantic` extra only** and are imported
lazily. Every read path falls back to pure-lexical FTS5 when they are absent,
the model cannot download, or `AGI_MEMORY_SEMANTIC_ENABLED=0`:

```bash
pipx install 'agi-memory[semantic]'   # Potion backend (one-time HF download)
```

Without the extra, `memory_recall`/`memory_recall_deep` behave exactly as
before — the `mode` parameter is accepted but resolves to `lexical`.

## Usage

```bash
# Paraphrase-tolerant recall (auto-backfills embeddings on read, bounded)
agi-memory recall "login problem" --mode hybrid
agi-memory recall "login problem" --deep --mode hybrid   # L1 hybrid + L2 lexical

# Pre-warm a large store (optional; reads backfill lazily anyway)
agi-memory semantic-index --max-obs 2000

# Force the old behavior
agi-memory recall "login problem" --mode lexical
```

MCP tools: `memory_recall` and `memory_recall_deep` accept
`mode: auto|lexical|hybrid|semantic` (default `auto` = hybrid when a backend
loads). `memory_semantic_index` backfills embeddings (`project`, `batch`,
`max_obs`). The L2 knowledge-graph side of `memory_recall_deep` stays
lexical; hybrid applies to the L1 working-memory side.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `AGI_MEMORY_SEMANTIC_ENABLED` | `auto` | `0` disables; `1`/`auto` enables when a backend loads |
| `AGI_MEMORY_SEMANTIC_MODEL` | `minishlab/potion-code-16M-v2` | HF id or local path (`SEMBLE_MODEL_NAME` honored as fallback) |
| `AGI_MEMORY_SEMANTIC_BACKEND` | `auto` | `model2vec`, or `hash` (deterministic stdlib fallback for tests/offline) |
| `AGI_MEMORY_RRF_K` | `60` | RRF fusion constant |
| `AGI_MEMORY_SEMANTIC_CANDIDATES` | `2000` | Max embedded rows scanned per query (newest-first) |

## Storage

Embeddings live in the same SQLite file as L1 (`semantic_embeddings` table:
`obs_id → model, dim, float32 vector`), written through `open_db()` like
everything else, so WAL/concurrency behavior is unchanged. Vectors are
L2-normalized at write time, making cosine similarity a dot product.
Re-embedding under a different model id coexists row-wise (keyed by
`obs_id` + `model`); stale rows for dropped observations are harmless
(the join filters `type != 'superseded'`) and can be rebuilt by deleting
the table — it is a derived cache, `observations` is the source of truth.

## Python API

```python
from agi_memory.layers import semantic_layer as sem
from agi_memory.layers.session_layer import SessionLayer
from agi_memory.recall import recall

l1 = SessionLayer(project="my-app")
be = sem.get_backend()  # raises RuntimeError with install hint when unavailable
sem.ensure_index(l1, be, project="my-app")          # backfill
hits, info = sem.hybrid_search("login problem", l1, be, limit=5)  # RRF fusion
r = recall("login problem", l1, None, mode="hybrid", backend=be)  # tiered wrapper
```

## Evals

`python3 tests/test_semantic.py` covers cosine/RRF units, index roundtrip,
hybrid-vs-lexical parity, FakeL1 degradation, and the MCP surface — stdlib
only, no network. Potion embedding quality itself is covered by the upstream
model benchmarks (CoIR/MTEB), not duplicated here.
