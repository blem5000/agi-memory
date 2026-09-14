# Running Evaluations & Tests

All tests run completely offline with zero API keys or external services.

## Scored evaluations — one per cognitive pillar

Each layer has its own graded suite reporting retrieval accuracy and latency, so
a regression shows up as a score drop rather than a still-passing assertion.

```bash
python3 tests/eval_l1.py   # L1 Epistemic:  working-memory recall      (10/10)
python3 tests/eval_l2.py   # L2 Semantic:   multi-hop graph traversal  (6/6)
python3 tests/eval_l3.py   # L3 Episodic:   session-history recall     (10/10)
python3 tests/eval_usage.py # Actionability: is a retrieved memory usable
python3 tests/eval_l4.py   # L4 Code Graph: callers/deps/impact vs a
                           #                fixture repo with known edges (25/25)
```

`eval_l3.py` seeds a multi-project session history and asks the questions a
developer asks between sessions ("what did I do about X"), then checks that
timelines stay project-scoped and that the recap names the most recent session.

`eval_usage.py` asks a different question from the rest. Every other suite
scores retrieval -- did the right record come back. This one also scores
**actionability**: whether the block handed to the agent carries the qualifier
needed to act on it correctly. A superseded decision returned without its
replacement, a constraint returned without the reason behind it, or a fuzzy hit
returned unlabelled all count as retrieved-but-unusable, and it reports that gap
as its own number.

It is a proxy and says so in its own output. Measuring real usage failure needs
a model in the loop; this measures whether correct use is *possible*, which is
the deterministic half. Verified sensitive: removing the rationale rendering,
the supersession pointer and the do-not-resume warning drops actionability from
5/5 to 2/5 while retrieval stays at 5/5.

`eval_l4.py` indexes a fixture repository whose call edges are true by
construction — Python, TypeScript and Go — and scores callers, dependencies,
blast radius and structure against that ground truth. Each eval exits non-zero
on any miss, so CI fails on an accuracy regression.

## Functional, adversarial and load suites

```bash
# Unit & layer tests, doc parity, tool registration
python3 tests/test_offline.py

# Verify stdio MCP server protocol handshake across all 16 tools
agi-integrate test

# Two machines syncing one vault, driven through the real CLI in isolated
# environments (separate HOME, vault and database per machine)
python3 tests/multi_machine_test.py

# Adversarial robustness: corrupt databases, hostile input, concurrency
python3 tests/chaos_test.py

# Comprehensive authentic production stress test
python3 tests/stress_test.py
```

## Full pre-commit chain

```bash
python3 tests/test_offline.py \
  && python3 tests/eval_l1.py && python3 tests/eval_l2.py \
  && python3 tests/eval_l3.py && python3 tests/eval_l4.py \
  && python3 tests/eval_usage.py \
  && agi-integrate test \
  && python3 tests/multi_machine_test.py \
  && python3 tests/chaos_test.py && python3 tests/stress_test.py
```

---
