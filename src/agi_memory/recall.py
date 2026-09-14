"""Tiered recall: L1 (SessionLayer) first, L2 (GraphLayer) only when needed.

Token-efficient by default: L1 returns a compact index; L2 is skipped
unless deep=True or L1 comes back thin.
"""
try:
    from agi_memory.layers.base import Hit, MemoryLayer
except ImportError:
    from layers.base import Hit, MemoryLayer


def _lexical_fallback(l1, query, limit):
    try:
        return l1.search(query, limit=limit)
    except Exception:
        return []


def _hybrid_recent(query, l1, limit, mode, backend):
    """Try hybrid RRF recall; return (hits, info). Never raises."""
    info = {"mode": "lexical", "note": ""}
    try:
        try:
            from agi_memory.layers import semantic_layer as sem
        except ImportError:
            from layers import semantic_layer as sem
    except Exception:
        return _lexical_fallback(l1, query, limit), info
    if not sem.semantic_enabled() or str(mode).lower() == "lexical":
        return _lexical_fallback(l1, query, limit), info
    if not (hasattr(l1, "_bodies_by_id") and hasattr(l1, "db_path")):
        # Test doubles / non-SQLite layers stay lexical.
        return _lexical_fallback(l1, query, limit), info
    try:
        be = backend or sem.get_backend()
    except Exception as e:  # model2vec missing, model not downloadable, ...
        info["note"] = str(e)
        return _lexical_fallback(l1, query, limit), info
    try:
        hits, hinfo = sem.hybrid_search(query, l1, be, limit=limit)
        hinfo.setdefault("note", "")
        return hits, hinfo
    except Exception:
        return _lexical_fallback(l1, query, limit), info


def recall(query: str, l1: MemoryLayer, l2: MemoryLayer | None = None,
           limit: int = 5, deep: bool = False, mode: str = "auto",
           backend=None) -> dict:
    recent, hinfo = _hybrid_recent(query, l1, limit, mode, backend)
    result: dict = {"recent": recent, "durable": [], "mode": hinfo.get("mode", "lexical")}
    if hinfo.get("note"):
        result["semantic_note"] = hinfo["note"]
    
    if hasattr(l1, "get_pinned_blocks"):
        try:
            pinned = l1.get_pinned_blocks(getattr(l1, "project", None))
            result["core"] = pinned
        except Exception:
            result["core"] = []

    if l2 is None:
        try:
            try:
                from agi_memory.layers.graph_layer import GraphLayer
            except ImportError:
                from layers.graph_layer import GraphLayer
            l2 = GraphLayer(project=getattr(l1, "project", None))
        except Exception:
            l2 = None

    if l2 is not None and (deep or len(recent) < 2):
        try:
            result["durable"] = l2.search(query, limit=limit)
        except Exception as e:  # L2 optional: degrade to L1, say why
            result["note"] = f"durable layer skipped: {type(e).__name__}"
    return result



def main(argv: list[str] | None = None) -> None:
    import argparse
    try:
        from agi_memory.layers.session_layer import SessionLayer
        from agi_memory.layers.graph_layer import GraphLayer
    except ImportError:
        from layers.session_layer import SessionLayer
        from layers.graph_layer import GraphLayer

    parser = argparse.ArgumentParser(description="Recall from agent session & durable memory.")
    parser.add_argument("query", help="Query text or keywords")
    parser.add_argument("--project", "-p", default=None, help="Filter by project name")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Hit limit (default 5)")
    parser.add_argument("--deep", "-d", action="store_true", help="Force deep recall from durable layer")
    parser.add_argument("--mode", "-m", default="auto",
                        choices=["auto", "lexical", "hybrid", "semantic"],
                        help="Recall mode: auto (hybrid when a backend loads), lexical, or hybrid/semantic (needs the 'semantic' extra)")
    args = parser.parse_args(argv)

    l1 = SessionLayer(project=args.project)
    l2 = GraphLayer(project=args.project)

    res = recall(args.query, l1, l2, limit=args.limit, deep=args.deep, mode=args.mode)
    print(f"[mode: {res.get('mode', 'lexical')}]")
    if res.get("semantic_note"):
        print(f"({res['semantic_note']})")
    if res.get("core"):
        print("## core memory (pinned)")
        for b in res["core"]:
            key = b.get("key") or b.get("block_key", "")
            cat = b.get("category", "system")
            content = b.get("content", "")
            print(f"- [{key}] ({cat}): {content}")
        print()
    print(f"## recent ({len(res['recent'])})")
    for h in res["recent"]:
        print(h.text)
    if res["durable"]:
        print(f"\n## durable ({len(res['durable'])})")
        for h in res["durable"]:
            print(h.text)
    elif res.get("note"):
        print(f"\n({res['note']})")


if __name__ == "__main__":
    main()

