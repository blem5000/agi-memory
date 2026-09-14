"""Actionability evaluation: is the retrieved memory usable, not merely found.

Every other eval in this repository scores retrieval -- did the right record
come back. None of them ask whether an agent reading that record would then do
the right thing. Those are different failures, and today they are
indistinguishable in the reported numbers: a memory that is retrieved and then
acted on wrongly fails the user exactly as a memory that was never found.

**What this can and cannot measure.** Measuring real usage failure needs a model
in the loop, and this project has no model and no network. So this measures the
honest deterministic half: whether the block handed to the agent *makes correct
use possible*. Each probe asserts two separate things.

  retrieval     -- the right record came back at all
  actionability -- the returned text carries the qualifier an agent needs in
                   order to act correctly on it, and does not present a
                   conditional, dead or approximate memory as a plain fact

A probe can pass retrieval and fail actionability. That gap is the number this
file exists to expose. It is a proxy for usage failure, not a measurement of it,
and the summary says so rather than letting a clean score imply more than it is.

Run:  python3 tests/eval_usage.py [--verbose]
"""
import _isolate  # noqa: F401,E402  -- must run before agi_memory resolves any path
import argparse
import sys
import tempfile
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.layers.episodic_layer import EpisodicLayer  # noqa: E402
from agi_memory.layers.session_layer import SessionLayer  # noqa: E402

PASS, FAIL = "  PASS ", "  FAIL "


class Probe:
    """One question, with what must come back and what must qualify it.

    `must_contain` is the qualifier that makes the memory safe to act on. Its
    absence is an actionability failure even when the right record was found --
    that is the whole point of the file.
    """

    def __init__(self, name, query, expect_text, must_contain=(), must_not_contain=()):
        self.name = name
        self.query = query
        self.expect_text = expect_text
        self.must_contain = must_contain
        self.must_not_contain = must_not_contain


def _seed(db: Path):
    """A store shaped like real use: a reversed decision, a reasoned one, a
    dead end, and a memory whose wording a later query will get wrong."""
    l1 = SessionLayer(db_path=db, project="usage")

    old = l1.record(
        text="Queue jobs in Redis; it is already deployed for caching.",
        title="Job Queue", project="usage", category="architecture")
    new = l1.record(
        text="Queue jobs in Postgres using SKIP LOCKED. Redis is no longer the queue.",
        title="Job Queue v2", project="usage", category="architecture",
        supersedes=f"#{old['id']}",
        rationale="losing queued jobs on a Redis restart cost us a billing run")
    l1.record(
        text="Rate limit the public API at 100 requests per minute per key.",
        title="Rate Limit", project="usage", category="decision",
        rationale="the downstream billing provider caps us at 120 rpm")
    l1.record(
        text="Serve thumbnails from a dedicated CDN bucket.",
        title="Thumbnail Delivery", project="usage", category="decision")
    l1.record(
        text="The worker pool size is set from the CPU count at startup.",
        title="Worker Pool", project="usage", category="architecture",
        origin="bootstrapped")

    ep = EpisodicLayer(db_path=db, project="usage")
    sid = ep.start_session(project="usage", goal="Move the queue onto Kafka")["session_id"]
    ep.end_session(sid, summary="Tried Kafka, hit ordering problems, stopped.",
                   project="usage")
    ep.set_outcome("abandoned", session_id=sid, project="usage")

    sid2 = ep.start_session(project="usage", goal="Ship the Postgres queue")["session_id"]
    ep.end_session(sid2, summary="Postgres queue shipped and verified.",
                   project="usage", outcome="completed")
    return l1, ep, old, new


PROBES = [
    Probe(
        # A line lifted out of git history is a description of what the code did
        # at one commit, not a decision anybody stands behind. Unmarked, it is
        # indistinguishable from one, and an agent will treat it as settled.
        "a bootstrapped memory admits it was never confirmed",
        "worker pool size CPU count", "worker pool",
        must_contain=("bootstrapped",),
    ),
    Probe(
        "a reversed decision is not returned as if it still stood",
        "Redis queue", "Redis",
        must_contain=("SUPERSEDED",),
    ),
    Probe(
        "the record that replaced it is reachable, not just its death noted",
        "Redis queue", "Redis",
        # A bare [SUPERSEDED] tells the agent the memory is dead and leaves it
        # with nowhere to go. The pointer is what makes it actionable.
        must_contain=("SUPERSEDED by #",),
    ),
    Probe(
        "a decision arrives with the reasoning that justified it",
        "Postgres SKIP LOCKED", "SKIP LOCKED",
        must_contain=("Why:", "billing run"),
    ),
    Probe(
        "a constraint carries the reason, so it is not tuned away blindly",
        "rate limit requests per minute", "100 requests",
        must_contain=("Why:", "120 rpm"),
    ),
    Probe(
        # A deletion typo. `thumbnials` -- a transposition -- is deliberately not
        # used here: it shares only 3 of 7 fragments with the stored word, below
        # the 50% coverage knee, so it does not retrieve at all. That ceiling is
        # eval_fuzzy's subject. This probe is about what happens once a fuzzy hit
        # IS returned: it must announce itself as approximate, because an agent
        # cannot otherwise tell a guess from a confident recall.
        "an approximate match is labelled, not passed off as a confident hit",
        "thumbnals", "Thumbnail",
        must_contain=("approximate match",),
    ),
]


def run_probes(l1, verbose: bool):
    retrieved = actionable = 0
    for probe in PROBES:
        hits = l1.search(probe.query, limit=5)
        blob = "\n".join(h.text for h in hits)
        found = probe.expect_text.lower() in blob.lower()
        missing = [m for m in probe.must_contain if m.lower() not in blob.lower()]
        present = [m for m in probe.must_not_contain if m.lower() in blob.lower()]
        usable = found and not missing and not present

        retrieved += bool(found)
        actionable += bool(usable)
        if verbose or not usable:
            mark = PASS if usable else FAIL
            print(f"{mark} {probe.name}")
            if not found:
                print(f"        retrieval failed: {probe.expect_text!r} not returned")
            elif missing:
                print(f"        retrieved, NOT actionable: missing {missing}")
            elif present:
                print(f"        retrieved, NOT actionable: unqualified {present}")
        else:
            print(f"{PASS} {probe.name}")
    return retrieved, actionable


def run_session_probes(ep, verbose: bool) -> tuple:
    """A recap is the one memory injected without being asked for, so an
    abandoned session presented as continuable is a usage failure by
    construction: nothing downstream ever questions it."""
    checks = []
    timeline = ep.get_timeline(project="usage", limit=5)
    abandoned = next((s for s in timeline if "Kafka" in (s.get("goal") or "")), None)
    completed = next((s for s in timeline if "Postgres" in (s.get("goal") or "")), None)

    if abandoned:
        recap = EpisodicLayer.format_recap(abandoned)
        checks.append(("an abandoned session is not recapped as work to continue",
                       "abandoned" in recap.lower() and "do not resume" in recap.lower()))
    else:
        checks.append(("an abandoned session is not recapped as work to continue", False))

    if completed:
        recap = EpisodicLayer.format_recap(completed)
        checks.append(("a finished session is not saddled with a false warning",
                       "do not resume" not in recap.lower()))
    else:
        checks.append(("a finished session is not saddled with a false warning", False))

    for name, ok in checks:
        print(f"{PASS if ok else FAIL} {name}")
    return sum(1 for _, ok in checks if ok), len(checks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    print("\nActionability - is the retrieved memory usable, not merely found")
    print("=" * 66)

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "usage.db"
        l1, ep, _old, _new = _seed(db)
        retrieved, actionable = run_probes(l1, args.verbose)
        sess_ok, sess_total = run_session_probes(ep, args.verbose)

    total = len(PROBES)
    print("=" * 66)
    print(f"retrieval    : {retrieved}/{total}")
    print(f"actionability: {actionable}/{total}   "
          f"(retrieved but not safely usable: {retrieved - actionable})")
    print(f"session recap: {sess_ok}/{sess_total}")
    print()
    print("This is a proxy. It measures whether the block handed to the agent")
    print("makes correct use possible, not whether a model then used it correctly;")
    print("measuring that needs a model in the loop. Read it as a floor.")
    passed = actionable + sess_ok
    wanted = total + sess_total
    return 0 if passed == wanted else 1


if __name__ == "__main__":
    sys.exit(main())
