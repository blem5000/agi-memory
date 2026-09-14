"""Optional hybrid semantic recall for L1 working memory (zero-deps core preserved).

Lexical FTS5/BM25 misses paraphrases ("login problem" vs "authentication
flow"). This module adds an *optional* vector sidecar fused with BM25 via
Reciprocal Rank Fusion (RRF, k=60), following the Semble recipe:

  lexical rank (FTS5/BM25) --\
                              +-- RRF --> fused ranking
  semantic rank (cosine) ----/

Design constraints (see rules/architecture.md):
- Core stays ``dependencies = []``. ``model2vec``/``numpy`` live in the
  ``semantic`` extra only and are imported lazily; every entry point falls
  back to pure-lexical when they are absent or the model cannot load.
- No module is named after a third-party package.
- All SQLite goes through ``layers/base.py::open_db``.
- Read paths never raise: failures degrade to lexical results.

Environment:
  AGI_MEMORY_SEMANTIC_ENABLED  auto|1|0 (default auto: hybrid when a backend loads)
  AGI_MEMORY_SEMANTIC_MODEL    HF id or local path (default
                               minishlab/potion-code-16M-v2; SEMBLE_MODEL_NAME
                               honored as fallback)
  AGI_MEMORY_SEMANTIC_BACKEND  auto|model2vec|hash (default auto; ``hash`` is a
                               deterministic stdlib fallback for tests/offline)
  AGI_MEMORY_RRF_K             RRF constant (default 60)
  AGI_MEMORY_SEMANTIC_CANDIDATES  max embedded rows scanned per query (default 2000)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .base import Hit, open_db

if TYPE_CHECKING:  # pragma: no cover - typing only, never a runtime import
    from .session_layer import SessionLayer

DEFAULT_MODEL = "minishlab/potion-code-16M-v2"
DEFAULT_DIM = 256
DEFAULT_RRF_K = 60
DEFAULT_CANDIDATES = 2000
DOC_TRUNCATE = 1500

_MODELS_CACHE: dict = {}


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or default).strip()


def active_model() -> str:
    """Resolve which embedding model id to use."""
    return (
        _env("AGI_MEMORY_SEMANTIC_MODEL")
        or _env("AGENT_MEMORY_SEMANTIC_MODEL")
        or _env("SEMBLE_MODEL_NAME")
        or DEFAULT_MODEL
    )


def rrf_k() -> int:
    try:
        return max(1, int(_env("AGI_MEMORY_RRF_K", str(DEFAULT_RRF_K))))
    except ValueError:
        return DEFAULT_RRF_K


def candidate_cap() -> int:
    try:
        return max(1, int(_env("AGI_MEMORY_SEMANTIC_CANDIDATES", str(DEFAULT_CANDIDATES))))
    except ValueError:
        return DEFAULT_CANDIDATES


def semantic_enabled() -> bool:
    """True unless explicitly disabled; auto-mode still needs a loadable backend."""
    val = (_env("AGI_MEMORY_SEMANTIC_ENABLED") or _env("AGENT_MEMORY_SEMANTIC_ENABLED") or "auto").lower()
    if val in ("0", "false", "no", "off", "lexical"):
        return False
    return True


_SYMBOL_RE = re.compile(
    r"(::|->|\.\w+\(|\(\)|[a-z]+[A-Z]\w*|\b\w+__\w+\b|_\w+|\b\w+_\w+\b|/[\w.-]+/)"
)


def is_symbol_query(query: str) -> bool:
    """Heuristic from Semble: symbol-like queries deserve more lexical weight."""
    q = query.strip()
    if not q:
        return False
    if _SYMBOL_RE.search(q):
        return True
    # Single identifier-ish token, e.g. `get_default_db`
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:]{2,60}", q))


# --- vector math (stdlib only; numpy arrays accepted via duck-typing) ---------

def _as_list(vec) -> list:
    if hasattr(vec, "tolist"):
        try:
            return list(vec.tolist())
        except Exception:
            pass
    return list(vec)


def normalize(vec) -> list:
    vals = [float(x) for x in _as_list(vec)]
    norm = math.sqrt(sum(v * v for v in vals))
    if norm <= 0:
        return [0.0] * len(vals)
    return [v / norm for v in vals]


def dot(a, b) -> float:
    la, lb = _as_list(a), _as_list(b)
    n = min(len(la), len(lb))
    return sum(float(la[i]) * float(lb[i]) for i in range(n))


def pack_vector(vec) -> bytes:
    return struct.pack("<%df" % len(vec), *[float(x) for x in _as_list(vec)])


def unpack_vector(blob: bytes, dim: int) -> list:
    try:
        vals = list(struct.unpack("<%df" % dim, bytes(blob)))
    except (struct.error, TypeError, ValueError):
        return [0.0] * dim
    return vals


def rrf_fuse(rank_lists: list, k: int = DEFAULT_RRF_K,
             weights: list | None = None) -> dict:
    """Fuse ranked id-lists into {ref: score}. Ranks are 1-based; earlier = better."""
    fused: dict = {}
    for idx, ranks in enumerate(rank_lists):
        w = 1.0 if not weights else float(weights[idx] if idx < len(weights) else 1.0)
        for rank, ref in enumerate(ranks, start=1):
            fused[ref] = fused.get(ref, 0.0) + w / (k + rank)
    return fused


# --- backends -----------------------------------------------------------------

class HashBackend:
    """Deterministic stdlib embedding fallback (tests / offline / no model).

    Char-trigram hashing trick into a fixed-dim, L2-normalized vector.
    Quality is *not* comparable to Potion; it exists so the hybrid plumbing,
    RRF fusion and persistence are testable with zero dependencies.
    """

    name = "hash"

    def __init__(self, dim: int = DEFAULT_DIM):
        self.dim = dim

    def _trigrams(self, text: str):
        t = f"  {text.lower()}  "
        for i in range(len(t) - 2):
            yield t[i:i + 3]

    def embed(self, texts: list) -> list:
        out = []
        for text in texts:
            if not (text or "").strip():
                out.append([0.0] * self.dim)
                continue
            vec = [0.0] * self.dim
            for tri in self._trigrams(text or ""):
                h = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16) % self.dim
                vec[h] += 1.0
            out.append(normalize(vec))
        return out

    @property
    def dim_actual(self) -> int:
        return self.dim


class Model2VecBackend:
    """Potion static-embedding backend (optional ``semantic`` extra).

    Loads ``minishlab/potion-code-16M-v2`` (or AGI_MEMORY_SEMANTIC_MODEL)
    via ``model2vec.StaticModel``. Static embeddings have no transformer
    forward pass at query time: milliseconds on CPU, tens of MB on disk.
    """

    name = "model2vec"

    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or active_model()
        self._model = None
        self._dim = 0

    def _load(self):
        if self._model is not None:
            return self._model
        if self.model_id in _MODELS_CACHE:
            self._model = _MODELS_CACHE[self.model_id]
            return self._model
        try:
            from model2vec import StaticModel
        except ImportError as e:
            raise RuntimeError(
                "semantic backend needs the optional 'semantic' extra: "
                "pipx install 'agi-memory[semantic]' (model2vec). "
                "Falling back to lexical search."
            ) from e
        try:
            model = StaticModel.from_pretrained(self.model_id)
        except Exception as e:
            raise RuntimeError(
                f"could not load embedding model {self.model_id!r} "
                f"(first run downloads it from Hugging Face): {e}"
            ) from e
        _MODELS_CACHE[self.model_id] = model
        self._model = model
        return model

    def embed(self, texts: list) -> list:
        model = self._load()
        vecs = model.encode(list(texts))
        try:
            rows = vecs.tolist()
        except AttributeError:
            rows = [list(r) for r in vecs]
        out = [normalize(r) for r in rows]
        if out:
            self._dim = len(out[0])
        return out

    @property
    def dim_actual(self) -> int:
        return self._dim or DEFAULT_DIM


def get_backend(prefer: str | None = None):
    """Return an embedding backend or raise RuntimeError with an install hint.

    ``prefer`` overrides AGI_MEMORY_SEMANTIC_BACKEND. ``hash`` never needs
    third-party packages; ``model2vec`` needs the ``semantic`` extra.
    """
    which = (prefer or _env("AGI_MEMORY_SEMANTIC_BACKEND", "auto")).lower()
    if which in ("hash", "test", "stdlib"):
        return HashBackend()
    if which in ("model2vec", "potion", "static"):
        return Model2VecBackend()
    # auto: model2vec when importable, else hash only when explicitly asked.
    try:
        import model2vec  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "no semantic backend available (model2vec not installed). "
            "Install with pipx install 'agi-memory[semantic]' or set "
            "AGI_MEMORY_SEMANTIC_BACKEND=hash for the stdlib fallback."
        )
    return Model2VecBackend()


def is_available(prefer: str | None = None) -> bool:
    if not semantic_enabled():
        return False
    try:
        be = get_backend(prefer)
        if isinstance(be, Model2VecBackend):
            be._load()
        return True
    except Exception:
        return False


# --- persistence (same SQLite file as L1, via open_db only) --------------------

EMBEDDINGS_DDL = """
CREATE TABLE IF NOT EXISTS semantic_embeddings (
    obs_id INTEGER PRIMARY KEY,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def _db_path(session_layer: SessionLayer) -> Path:
    return Path(session_layer.db_path)


def ensure_table(db_path: Path | str) -> None:
    con = open_db(db_path)
    try:
        con.execute(EMBEDDINGS_DDL)
        con.commit()
    finally:
        con.close()


def doc_text(title: str | None, facts: str | None, narrative: str | None) -> str:
    """Compose the embeddable document for one observation row."""
    parts = []
    if title:
        parts.append(title.strip())
    if facts:
        f = facts.strip()
        if f.startswith("["):
            try:
                items = json.loads(f)
                f = " ".join(str(i) for i in items if isinstance(i, str))
            except (ValueError, TypeError):
                pass
        parts.append(f)
    if narrative:
        parts.append(narrative.strip())
    doc = " ".join(p for p in parts if p)
    return doc[:DOC_TRUNCATE]


def ensure_index(session_layer: SessionLayer, backend=None,
                 project: str | None = None, batch: int = 64,
                 max_obs: int | None = None) -> dict:
    """Embed observations missing vectors. Returns counts; never raises."""
    res = {"embedded": 0, "skipped": 0, "model": "", "dim": 0}
    try:
        db_path = _db_path(session_layer)
        if not db_path.exists():
            return res
        be = backend or get_backend()
        model_id = getattr(be, "model_id", None) or f"hash-{DEFAULT_DIM}"
        res.update(model=model_id)
        ensure_table(db_path)
        proj = project if project is not None else getattr(session_layer, "project", None)
        con = open_db(db_path)
        try:
            sql = ("SELECT o.id, o.title, o.facts, o.narrative FROM observations o "
                   "LEFT JOIN semantic_embeddings e ON e.obs_id = o.id AND e.model = ? "
                   "WHERE e.obs_id IS NULL AND o.type != 'superseded'")
            args: list = [model_id]
            if proj in ("agi-memory", "agent-memory"):
                sql += " AND o.project IN ('agi-memory','agent-memory')"
            elif proj:
                sql += " AND o.project = ?"
                args.append(proj)
            sql += " ORDER BY o.id DESC"
            if max_obs:
                sql += " LIMIT ?"
                args.append(int(max_obs))
            rows = con.execute(sql, args).fetchall()
        finally:
            con.close()
        if not rows:
            return res
        dim = 0
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        step = max(1, int(batch or 64))
        for off in range(0, len(rows), step):
            chunk = rows[off:off + step]
            try:
                vecs = be.embed([doc_text(t, f, n) for (_, t, f, n) in chunk])
            except Exception:
                res["skipped"] += len(chunk)
                continue
            if vecs:
                dim = len(vecs[0])
            con = open_db(db_path)
            try:
                for (oid, _, _, _), vec in zip(chunk, vecs):
                    if not any(vec):
                        res["skipped"] += 1
                        continue
                    con.execute(
                        "INSERT INTO semantic_embeddings (obs_id, model, dim, vector, updated_at) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(obs_id) DO UPDATE SET model=excluded.model, dim=excluded.dim, "
                        "vector=excluded.vector, updated_at=excluded.updated_at",
                        (oid, model_id, len(vec), pack_vector(vec), now),
                    )
                    res["embedded"] += 1
                con.commit()
            except sqlite3.Error:
                try:
                    con.rollback()
                except sqlite3.Error:
                    pass
                res["skipped"] += len(chunk)
            finally:
                con.close()
        res["dim"] = dim
        return res
    except Exception:
        return res


def _fetch_vectors(db_path: Path, model_id: str, proj: str | None,
                   cap: int) -> list:
    """Return [(obs_id, vector)] newest-first, project-scoped. Empty on any error."""
    try:
        if not db_path.exists():
            return []
        con = open_db(db_path, readonly=True)
        try:
            sql = ("SELECT o.id, e.vector, e.dim FROM semantic_embeddings e "
                   "JOIN observations o ON o.id = e.obs_id "
                   "WHERE e.model = ? AND o.type != 'superseded'")
            args: list = [model_id]
            if proj in ("agi-memory", "agent-memory"):
                sql += " AND o.project IN ('agi-memory','agent-memory')"
            elif proj:
                sql += " AND o.project = ?"
                args.append(proj)
            sql += " ORDER BY o.id DESC LIMIT ?"
            args.append(cap)
            rows = con.execute(sql, args).fetchall()
        finally:
            con.close()
        return [(r[0], unpack_vector(r[1], r[2])) for r in rows]
    except sqlite3.Error:
        return []


def semantic_rank(query: str, session_layer: SessionLayer, backend,
                  project: str | None = None, limit: int = 20,
                  cap: int | None = None) -> list:
    """Cosine-ranked [(obs_id_str, score)] for the query. Empty on any error."""
    try:
        model_id = getattr(backend, "model_id", None) or f"hash-{DEFAULT_DIM}"
        qvec = backend.embed([query])[0]
        if not any(qvec):
            return []
        proj = project if project is not None else getattr(session_layer, "project", None)
        cands = _fetch_vectors(_db_path(session_layer), model_id, proj, cap or candidate_cap())
        scored = [(str(oid), dot(qvec, vec)) for oid, vec in cands]
        scored = [(oid, s) for oid, s in scored if s > 0]
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored[:limit]
    except Exception:
        return []


# --- hybrid entry point ---------------------------------------------------------

def hybrid_search(query: str, session_layer: SessionLayer, backend=None,
                  limit: int = 5, lexical_limit: int | None = None,
                  semantic_limit: int | None = None, k: int | None = None,
                  project: str | None = None) -> tuple:
    """Fuse BM25 lexical hits with cosine semantic hits via RRF.

    Returns (hits, info) where info carries mode/counts/notes for callers.
    With ``backend=None`` (or any failure) this is pure lexical: the read
    path never raises and never returns less than FTS5 alone would.
    """
    proj = project if project is not None else getattr(session_layer, "project", None)
    lex_n = lexical_limit or max(limit * 4, 10)
    sem_n = semantic_limit or max(limit * 4, 10)
    try:
        lex_hits = session_layer.search(query, lex_n)
    except Exception:
        lex_hits = []
    lex_rank = [h.ref for h in lex_hits if h.ref]

    info: dict = {"mode": "lexical", "lexical_count": len(lex_rank),
                  "semantic_count": 0, "note": ""}
    if backend is None:
        fused = rrf_fuse([lex_rank], k=k or rrf_k())
        order = sorted(fused, key=fused.get, reverse=True)[:limit]  # type: ignore[arg-type]
        try:
            hits = session_layer._bodies_by_id([str(i) for i in order])
        except Exception:
            hits = lex_hits[:limit]
        return hits, info

    try:
        # Backfill on read (bounded): new memories become searchable without a
        # separate indexing step; failures are swallowed by ensure_index.
        ensure_index(session_layer, backend, project=proj, max_obs=500)
        sem_ranked = semantic_rank(query, session_layer, backend,
                                   project=proj, limit=sem_n)
    except Exception:
        sem_ranked = []
    sem_rank = [oid for oid, _ in sem_ranked]
    info["semantic_count"] = len(sem_rank)

    if not sem_rank:
        info["note"] = "semantic side empty (no embeddings yet); lexical only"
        fused = rrf_fuse([lex_rank], k=k or rrf_k())
    else:
        info["mode"] = "hybrid"
        if is_symbol_query(query):
            # Semble-style adaptive weighting: identifiers rank lexically.
            fused = rrf_fuse([lex_rank, sem_rank], k=k or rrf_k(), weights=[2.0, 1.0])
            info["note"] = "symbol-like query: lexical weight x2"
        else:
            fused = rrf_fuse([lex_rank, sem_rank], k=k or rrf_k())
    order = sorted(fused, key=fused.get, reverse=True)[:limit]  # type: ignore[arg-type]
    lex_pos = {ref: i + 1 for i, ref in enumerate(lex_rank)}
    sem_pos = {oid: i + 1 for i, (oid, _) in enumerate(sem_ranked)}
    try:
        hits = session_layer._bodies_by_id([str(i) for i in order])
    except Exception:
        hits = []
    for h in hits:
        h.source = f"{h.source}+semantic" if info["mode"] == "hybrid" else h.source
        h.score = float(fused.get(h.ref, 0.0))
        h.meta = {"mode": info["mode"], "lex_rank": lex_pos.get(h.ref),
                  "sem_rank": sem_pos.get(h.ref)}
    if not hits:
        hits = lex_hits[:limit]
    return hits, info
