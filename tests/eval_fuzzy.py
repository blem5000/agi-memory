"""Degraded-query evaluation: how much recall is lost when a question is
phrased the way a real agent phrases it, rather than the way the memory was
written.

This measures a baseline, it does not assert one. Each probe first runs the
EXACT query; only if that hits is the degraded variant counted, so the number
reported is the loss caused by degradation and not a pre-existing miss.

Categories, in increasing distance from string matching:

  morphological  authenticate      <- authentication      (stemming)
  typo           autentication     <- authentication      (edit distance)
  identifier     get_user_by_id    <- getUserById         (tokenization)
  abbreviation   cfg               <- configuration       (alias)
  paraphrase     login             <- authentication      (semantics)

Only the first three are reachable by fuzzy string matching. Paraphrase is
listed to show what fuzz can NOT buy: it needs curated aliases or host-side
query expansion, not a looser matcher.
"""
import _isolate  # noqa: F401,E402  -- must run before agi_memory resolves any path
import argparse
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.layers.session_layer import SessionLayer
from agi_memory.layers.graph_layer import GraphLayer
from agi_memory.layers.episodic_layer import EpisodicLayer
from agi_memory.layers.code_layer import CodeLayer

# --- corpus -------------------------------------------------------------------

MEMORIES = [
    ("Auth migration", "Migrated authentication to short-lived JWT tokens issued by the auth service."),
    ("Pricing responses", "Responses are cached in Redis with a 300 second expiration on the pricing endpoint."),
    ("Retry strategy", "Outbound webhooks retry with exponential backoff, capped at five attempts."),
    ("Schema decision", "Subscription records are normalized into a separate billing table."),
    ("Deployment", "Containers are deployed to Kubernetes with a rolling update strategy."),
    ("Configuration", "Environment configuration is loaded from a single settings module at startup."),
]

# (exact query that should hit, {category: degraded variant})
PROBES = [
    # Every degraded query below is checked by test_probe_hygiene() to share no
    # word stem with the corpus, so a hit means the matcher bridged the gap
    # rather than the probe leaking a literal corpus word.
    ("authentication", {
        "morphological": "authenticate",
        "typo": "autentication",
        "paraphrase": "login",
    }),
    ("cached", {
        "morphological": "caching",
        "typo": "cachd",
        "paraphrase": "memoization",
    }),
    ("retry", {
        "morphological": "retrying",
        "typo": "rety",
        "paraphrase": "resend",
    }),
    ("normalized", {
        "morphological": "normalize",
        "typo": "normlized",
        "paraphrase": "decomposition",
    }),
    ("Kubernetes", {
        "typo": "Kubernets",
        "abbreviation": "k8s",
        "paraphrase": "node pool",
    }),
    ("configuration", {
        "morphological": "configure",
        "typo": "configuartion",
        "abbreviation": "cfg",
        "paraphrase": "tunables",
    }),
]

# (query, a distinctive phrase that must appear in the TOP hit)
# Recall without precision is worthless: a matcher that returns everything scores
# 100% recall and is useless. The budget below is asserted before and after any
# matching change.
PRECISION_PROBES = [
    ("authentication JWT", "JWT"),
    ("Redis expiration", "Redis"),
    ("webhook backoff", "backoff"),
    ("billing table", "billing"),
    ("Kubernetes rolling update", "Kubernetes"),
    ("environment settings module", "settings"),
]

# Council-mandated budget, fixed before the matching work started:
#   precision must not regress at all. Recall may rise; precision may not fall.
PRECISION_BUDGET = 1.0

# --- unanswerable probes -----------------------------------------------------
# Recall with no negative class is gameable: a matcher that returns something
# for every query scores 100% above while telling the caller nothing. Two
# classes, because they fail differently.

# No corpus word in common. The store must return NOTHING -- not "something
# close": an invented answer gets acted on, a miss gets rephrased.
UNANSWERABLE_NO_OVERLAP = [
    "quantum refrigerator warranty",
    "portuguese patent filing deadline",
    "alpine weather forecast for hiking",
]

# Shares vocabulary with the corpus, yet no record answers the query -- the
# shape that filled 25/30 slots with irrelevant records on a 3,000-record
# store. Construction rule, enforced by test_probe_hygiene(): no single
# record may hold more than two of the probe's terms. A record matching
# three terms is a topical match, and bm25 scores topicality, not
# answerhood -- excluding that case keeps the gate honest rather than
# tuned. Measured on this fixture: top-1 1.685..2.668 vs answerable floor
# 3.371. The gate below asserts that separation on this fixture only; it is
# NOT an abstention threshold -- nothing in the store reads score to decide
# whether to answer.
UNANSWERABLE_SHARED = [
    "redis cluster administration",
    "jwt billing expiration policy",
    "kubernetes configuration retry strategy",
    "authentication kubernetes billing",
]

CODE_FIXTURE = {
    # Only snake_case is defined. Querying the camelCase spelling must therefore
    # be a real fuzzy lookup, not a hit on a different symbol that happens to exist.
    "svc/users.py": "def get_user_by_id(uid):\n    return uid\n\n"
                    "def load_profile(uid):\n    return get_user_by_id(uid)\n",
    # A reader asked how much the code graph recovers when wording changes but
    # the symbol stays stable. The honest answer was that the identifier
    # category had ONE probe behind it, which is a pass rather than a
    # measurement. These add the shapes that actually occur across languages:
    # camelCase and PascalCase from JS/TS and Dart, kebab from CSS and CLI
    # flags, SCREAMING_SNAKE constants, and dotted or slashed member paths.
    "svc/billing.py": "def refund_payment(charge_id):\n    return charge_id\n\n"
                      "def issue_credit_note(charge_id):\n    return refund_payment(charge_id)\n",
    # The constant is referenced, not merely declared: get_callers traverses
    # CALLS/IMPORTS/EXTENDS/IMPLEMENTS, so a symbol nothing refers to has no
    # callers and its probe measures nothing.
    "svc/cache.py": "MAX_RETRY_COUNT = 5\n\n"
                    "def invalidate_cache_entry(key):\n"
                    "    for _ in range(MAX_RETRY_COUNT):\n        pass\n    return key\n\n"
                    "def purge(key):\n    return invalidate_cache_entry(key)\n",
    "svc/auth_service.py": "class AuthTokenStore:\n"
                           "    def rotate_signing_key(self):\n        return True\n\n"
                           "def bootstrap():\n    return AuthTokenStore().rotate_signing_key()\n",
}

# (exact symbol that resolves, {category: degraded spelling})
CODE_PROBES = [
    ("get_user_by_id", {
        "identifier": "getUserById",
        "typo": "get_user_by_i",
        "morphological": "get_users_by_id",
    }),
    ("get_user_by_id", {"identifier": "GetUserById"}),        # PascalCase
    ("get_user_by_id", {"identifier": "get-user-by-id"}),     # kebab
    ("get_user_by_id", {"identifier": "getuserbyid"}),        # flattened
    ("refund_payment", {
        "identifier": "refundPayment",
        "typo": "refund_paymnt",
        "morphological": "refund_payments",
    }),
    ("refund_payment", {"identifier": "RefundPayment"}),
    ("refund_payment", {"identifier": "refund-payment"}),
    ("invalidate_cache_entry", {
        "identifier": "invalidateCacheEntry",
        "typo": "invalidate_cach_entry",
        "morphological": "invalidate_cache_entries",
    }),
    ("invalidate_cache_entry", {"identifier": "InvalidateCacheEntry"}),
    ("MAX_RETRY_COUNT", {"identifier": "maxRetryCount"}),      # constant vs camel
    ("MAX_RETRY_COUNT", {"identifier": "max_retry_count"}),    # constant vs snake
    ("rotate_signing_key", {
        "identifier": "rotateSigningKey",
        "typo": "rotate_signng_key",
        "morphological": "rotate_signing_keys",
    }),
    ("rotate_signing_key", {"identifier": "AuthTokenStore.rotateSigningKey"}),  # member path
    ("AuthTokenStore", {"identifier": "auth_token_store"}),    # class in snake
    ("AuthTokenStore", {"identifier": "authTokenStore"}),
]


def test_probe_hygiene() -> list:
    """Reject probes that would measure nothing.

    The rule differs by category, because the categories ask different things:

      morphological / typo  a shared stem is THE POINT ("authenticate" vs
                            "authentication"), so only a verbatim corpus word
                            is disqualifying -- that would be an exact match
                            wearing a costume.
      abbreviation /        the matcher has to bridge a gap no stemmer can, so
      paraphrase            sharing any stem with the corpus means a hit proves
                            nothing about semantics.

    The first two runs of this file reported 100% on categories that were in
    fact measuring corpus leakage, which is why this check exists.
    """
    corpus = " ".join(f"{t} {b}" for t, b in MEMORIES).lower()
    corpus_words = set(re.findall(r"[a-z0-9]+", corpus))
    leaks = []
    for exact, variants in PROBES:
        for category, degraded in variants.items():
            tokens = re.findall(r"[a-z0-9]+", degraded.lower())
            if degraded.lower() == exact.lower():
                leaks.append(f"{category}: {degraded!r} is identical to the exact query")
                continue
            if category in ("morphological", "typo"):
                verbatim = [t for t in tokens if t in corpus_words]
                if verbatim:
                    leaks.append(f"{category}: {degraded!r} appears verbatim in the corpus "
                                 f"({verbatim[0]!r}) -- that is an exact match, not a degradation")
                continue
            for token in tokens:
                shared = next((w for w in corpus_words
                               if len(token) >= 4 and len(w) >= 4
                               and (token.startswith(w[:4]) or w.startswith(token[:4]))), None)
                if shared:
                    leaks.append(f"{category}: {degraded!r} shares a stem with corpus word {shared!r}")
                    break
    # Unanswerable probes carry their own rules: the no-overlap class must
    # share no corpus word at all (else it is an answerable query wearing a
    # costume), and the shared class must spread its terms (else a record
    # that matches three of them will legitimately outscore answerable
    # probes and the separation gate would be measuring the fixture, not
    # the matcher).
    for q in UNANSWERABLE_NO_OVERLAP:
        shared = set(re.findall(r"[a-z0-9]+", q.lower())) & corpus_words
        if shared:
            leaks.append(f"unanswerable probe {q!r} shares corpus word "
                         f"{sorted(shared)[0]!r} -- it would not be unanswerable")
    for q in UNANSWERABLE_SHARED:
        q_tokens = set(re.findall(r"[a-z0-9]+", q.lower()))
        for title, body in MEMORIES:
            rec = set(re.findall(r"[a-z0-9]+", f"{title} {body}".lower()))
            overlap = q_tokens & rec
            if len(overlap) > 2:
                leaks.append(f"unanswerable probe {q!r} puts {len(overlap)} terms in one "
                             f"record ({title!r}: {sorted(overlap)}) -- bm25 would score "
                             "it like a topical match")
                break
    return leaks


def probe(fn, query: str) -> bool:
    try:
        return bool(fn(query))
    except Exception:
        return False


def main():
    argparse.ArgumentParser(description="Measure recall loss on degraded queries.").parse_args()
    leaks = test_probe_hygiene()
    if leaks:
        print("\nPROBE HYGIENE FAILURE -- these would measure nothing:")
        for l in leaks:
            print(f"  - {l}")
        sys.exit(2)

    results = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # layer -> cat -> [hits, eligible]
    skipped = []

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "fuzzy.db"

        l1 = SessionLayer(db_path=db, project="fuzz")
        gl = GraphLayer(db_path=Path(tmp) / "fuzzy_l2.db")
        for title, body in MEMORIES:
            l1.record(body, title=title, project="fuzz")
            gl.add(f"[fuzz] {title}: {body}")

        ep_db = Path(tmp) / "fuzzy_l3.db"
        for title, body in MEMORIES:
            ep = EpisodicLayer(db_path=ep_db, project="fuzz")
            sid = ep.start_session(project="fuzz", goal=title)["session_id"]
            ep.end_session(sid, summary=body, project="fuzz")
        ep = EpisodicLayer(db_path=ep_db, project="fuzz")

        layers = [
            ("L1 epistemic", lambda q: l1.search(q, limit=5)),
            ("L2 semantic", lambda q: gl.search(q, limit=5)),
            ("L3 episodic", lambda q: ep.search(q, limit=5)),
        ]

        for layer_name, fn in layers:
            for exact, variants in PROBES:
                if not probe(fn, exact):
                    skipped.append(f"{layer_name}: exact {exact!r} already misses")
                    continue
                for category, degraded in variants.items():
                    hit = probe(fn, degraded)
                    results[layer_name][category][0] += hit
                    results[layer_name][category][1] += 1

        # L4 works on symbol names, so it gets identifier-shape probes
        root = Path(tmp) / "repo"
        for rel, body in CODE_FIXTURE.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
        cl = CodeLayer(db_path=Path(tmp) / "fuzzy_l4.db", project="fuzz")
        cl.index_directory(root, project="fuzz")
        cl_fn = lambda q: cl.get_callers(q, project="fuzz")

        for exact, variants in CODE_PROBES:
            if not probe(cl_fn, exact):
                skipped.append(f"L4 code graph: exact {exact!r} already misses")
                continue
            for category, degraded in variants.items():
                hit = probe(cl_fn, degraded)
                results["L4 code graph"][category][0] += hit
                results["L4 code graph"][category][1] += 1

        # Every layer that was loosened must be checked, not just L1.
        print("\nPrecision — is the RIGHT memory ranked first?\n")
        prec_hits = prec_total = 0
        for layer_name, fn in layers:
            layer_hits = 0
            for query, expected_in_top in PRECISION_PROBES:
                hits = fn(query)
                top = hits[0].text if hits else ""
                ok = expected_in_top.lower() in top.lower()
                layer_hits += ok
                if not ok:
                    print(f"FAIL {layer_name} :: {query:<30} -> "
                          f"{(top[:52] + '...') if top else '(no hits)'}")
            prec_hits += layer_hits
            prec_total += len(PRECISION_PROBES)
            print(f"  {layer_name:<14} {layer_hits}/{len(PRECISION_PROBES)} "
                  f"({layer_hits / len(PRECISION_PROBES):.0%})")
        precision = prec_hits / prec_total
        print(f"\nPrecision: {prec_hits}/{prec_total} = {precision:.0%} "
              f"(budget: {PRECISION_BUDGET:.0%}, must not regress)")

        # Unanswerable probes, L1 only: this is the layer whose matcher was
        # loosened; L2-L4 have their own scoring and own negative cases.
        print("\nUnanswerable — no record answers; does the store invent one?\n")
        gate_fail = []
        for q in UNANSWERABLE_NO_OVERLAP:
            hits = l1.search(q, limit=5)
            if hits:
                gate_fail.append(f"no-overlap {q!r} returned {len(hits)} hits "
                                 f"(top1 score {hits[0].score:.3f})")
                print(f"FAIL {q} -> invented answer: {hits[0].text[:60]!r}")
            else:
                print(f"  PASS 0 hits :: {q}")
        ans = []
        for q, must in PRECISION_PROBES:
            hits = l1.search(q, limit=5)
            if hits and must.lower() in hits[0].text.lower():
                ans.append(hits[0].score)
        un = []
        for q in UNANSWERABLE_SHARED:
            hits = l1.search(q, limit=5)
            un.append(hits[0].score if hits else 0.0)
        floor = min(ans) if ans else float("nan")
        ceiling = max(un)
        separated = bool(ans) and floor > ceiling
        print(f"\n  shared-overlap top-1 ceiling {ceiling:.3f} vs answerable "
              f"floor {floor:.3f} -> {'separated' if separated else 'OVERLAPPED'}")
        if not separated:
            gate_fail.append(f"score separation lost: floor {floor:.3f} <= ceiling {ceiling:.3f}")
        if gate_fail:
            print("\nUNANSWERABLE GATE FAILURE:")
            for f in gate_fail:
                print(f"  - {f}")
            sys.exit(1)

    categories = ["morphological", "typo", "identifier", "abbreviation", "paraphrase"]
    print("\nRecall on degraded queries (exact form verified to hit first)\n")
    header = f"{'Layer':<16}" + "".join(f"{c[:13]:>15}" for c in categories)
    print(header)
    print("-" * len(header))
    totals = defaultdict(lambda: [0, 0])
    for layer in ("L1 epistemic", "L2 semantic", "L3 episodic", "L4 code graph"):
        row = f"{layer:<16}"
        for cat in categories:
            hits, elig = results[layer][cat]
            if not elig:
                row += f"{'-':>15}"
                continue
            totals[cat][0] += hits
            totals[cat][1] += elig
            row += f"{f'{hits}/{elig} ({hits / elig:.0%})':>15}"
        print(row)
    print("-" * len(header))
    row = f"{'ALL':<16}"
    for cat in categories:
        hits, elig = totals[cat]
        row += f"{f'{hits}/{elig} ({hits / elig:.0%})':>15}" if elig else f"{'-':>15}"
    print(row + "\n")

    if skipped:
        print("Skipped (exact query already missed, degradation not measurable):")
        for s in skipped:
            print(f"  - {s}")
        print()

    overall_hits = sum(h for h, _ in totals.values())
    overall_elig = sum(e for _, e in totals.values())
    print(f"Baseline degraded-query recall: {overall_hits}/{overall_elig} "
          f"= {overall_hits / overall_elig:.0%}\n")
    if precision < PRECISION_BUDGET:
        print(f"\nPRECISION REGRESSION: {precision:.0%} < budget {PRECISION_BUDGET:.0%}. "
              f"A looser matcher that returns the wrong memory is worse than a miss.")
        sys.exit(1)
    print("Recall is report-only; precision is enforced against the budget.")


if __name__ == "__main__":
    main()
