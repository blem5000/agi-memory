"""Hybrid semantic recall checks: stdlib only, no network, no model download.

Uses HashBackend (deterministic) so the RRF fusion, persistence and MCP
wiring are testable offline. Real Potion/model2vec quality is covered by
the upstream model benchmarks, not here.
"""
import os
import sys
import tempfile
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ["AGI_MEMORY_SEMANTIC_BACKEND"] = "hash"

from agi_memory.layers import semantic_layer as sem
from agi_memory.layers.base import Hit, MemoryLayer
from agi_memory.layers.session_layer import SessionLayer
from agi_memory.recall import recall


# --- vector math / RRF units ---------------------------------------------------

a = sem.normalize([3.0, 4.0])
assert abs(a[0] - 0.6) < 1e-9 and abs(a[1] - 0.8) < 1e-9, a
assert sem.dot([1.0, 0.0], [1.0, 0.0]) == 1.0
assert sem.dot([1.0, 0.0], [0.0, 1.0]) == 0.0

blob = sem.pack_vector([0.5, -0.25])
assert sem.unpack_vector(blob, 2) == [0.5, -0.25]

fused = sem.rrf_fuse([["x", "y"], ["y", "z"]], k=60)
assert fused["y"] > fused["x"] and fused["y"] > fused["z"], fused
assert sem.rrf_fuse([], k=60) == {}

assert sem.is_symbol_query("get_default_db")
assert sem.is_symbol_query("Foo::bar")
assert not sem.is_symbol_query("how is authentication handled")

# HashBackend is deterministic and normalized
hb = sem.HashBackend()
v1 = hb.embed(["authentication flow"])[0]
v2 = hb.embed(["authentication flow"])[0]
assert v1 == v2 and abs(sum(x * x for x in v1) - 1.0) < 1e-9
assert hb.embed([""])[0] == [0.0] * sem.DEFAULT_DIM

# Backend resolution never needs third-party packages at import time; the
# stdlib hash fallback is always constructible. (Deliberately no _load()
# probe here: that would download the Potion weights on machines with
# model2vec installed, making this offline test network-dependent.)
assert isinstance(sem.get_backend("hash"), sem.HashBackend)
try:
    import model2vec  # noqa: F401
    print("note: model2vec installed; Potion backend loadable")
except ImportError:
    print("note: model2vec NOT installed; stdlib hash fallback in effect")

# --- hybrid over a real temp SQLite store --------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "mem.db"
    l1 = SessionLayer(project="proj", db_path=db)
    l1.record("Use JWT middleware with the jose library in src/middleware/auth.ts",
              title="JWT auth uses jose", project="proj", category="architecture")
    l1.record("Always index every new user lookup field before shipping",
              title="Index lookup fields", project="proj", category="convention")
    l1.record("Prefer edge-compatible jose over jsonwebtoken for auth",
              title="Prefer jose", project="proj", category="decision")

    be = sem.HashBackend()
    idx = sem.ensure_index(l1, be, project="proj")
    assert idx["embedded"] == 3, idx
    # Second run: nothing missing
    idx2 = sem.ensure_index(l1, be, project="proj")
    assert idx2["embedded"] == 0, idx2

    # Lexical baseline still works
    lex = l1.search("jose", 5)
    assert len(lex) >= 1, lex

    # Hybrid returns hits with fusion metadata and never less than lexical
    hits, info = sem.hybrid_search("jose middleware", l1, be, limit=3, project="proj")
    assert info["mode"] == "hybrid", info
    assert len(hits) >= 1, hits
    assert all(h.meta.get("mode") == "hybrid" for h in hits), [h.meta for h in hits]

    # Pure-lexical mode is byte-identical in behavior to SessionLayer.search
    hits_lex, info_lex = sem.hybrid_search("jose", l1, None, limit=3, project="proj")
    assert info_lex["mode"] == "lexical", info_lex
    assert [h.ref for h in hits_lex] == [h.ref for h in l1.search("jose", 12)][:3]

    # recall() honors mode and stays backward compatible
    r = recall("jose middleware", l1, None, limit=3, mode="hybrid", backend=be)
    assert r["mode"] == "hybrid" and len(r["recent"]) >= 1, r
    r2 = recall("jose", l1, None, limit=3)  # default auto; hash backend forced by env
    assert r2["mode"] in ("hybrid", "lexical"), r2
    r3 = recall("jose", l1, None, limit=3, mode="lexical")
    assert r3["mode"] == "lexical", r3

    # FakeL1 doubles (no db_path) degrade to lexical instead of raising
    class FakeL1(MemoryLayer):
        name = "fake-l1"

        def search(self, query, limit=5):
            return [Hit(text="x", source="fake-l1", ref="1")][:limit]

    rf = recall("anything", FakeL1(), None, mode="hybrid", backend=be)
    assert rf["mode"] == "lexical" and len(rf["recent"]) == 1, rf

# --- MCP surface ------------------------------------------------------------------

from agi_memory.mcp_server import TOOLS, WRITE_TOOLS, call_tool

names = {t["name"] for t in TOOLS}
assert "memory_semantic_index" in names, names
for t in TOOLS:
    if t["name"] in ("memory_recall", "memory_recall_deep"):
        assert "mode" in t["inputSchema"]["properties"], t["name"]
assert "memory_semantic_index" in WRITE_TOOLS

with tempfile.TemporaryDirectory() as tmp:
    os.environ["AGI_MEMORY_DB"] = str(Path(tmp) / "mcp.db")
    try:
        l1m = SessionLayer(project="mcp-proj")
        l1m.record("Ship only with an index on the new lookup column",
                   title="Lookup index rule", project="mcp-proj")
        out = call_tool("memory_recall", {"query": "lookup", "project": "mcp-proj",
                                          "limit": 3, "mode": "lexical"})
        assert "Lookup index rule" in out, out
        out_h = call_tool("memory_recall", {"query": "lookup column",
                                            "project": "mcp-proj", "limit": 3,
                                            "mode": "hybrid"})
        assert "Lookup index rule" in out_h, out_h
        idx_out = call_tool("memory_semantic_index", {"project": "mcp-proj"})
        assert "Semantic index" in idx_out, idx_out
    finally:
        del os.environ["AGI_MEMORY_DB"]

print("test_semantic: OK")
