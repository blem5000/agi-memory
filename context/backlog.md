# Backlog & Open Findings

Durable record of known defects, deferred work, and the reasoning behind
decisions that are easy to re-litigate. Each item states the evidence, so a
future session can act without re-deriving it.

Last reviewed: 2026-09-13 (council-reviewed after backlog completion).

---

## 1. Vault git-sync silently diverges on concurrent machines — CONFIRMED BUG

**Severity: high.** Data isolation in a headline feature ("cross-device git sync").

Two machines that both record memories between syncs will permanently stop
sharing them, and nothing tells the user.

**Reproduction** (verified against a bare repo, two clones):

```
m1 and m2 both append a line to observations.jsonl, both commit
m1 pushes first
m2: git pull --rebase   -> rc=1, "Could not apply <sha>... m2 append"
    sync.py             -> rebase --abort, sets status "pull_offline"
    m2's vault          -> missing m1's record
    m2: git push        -> REJECTED (non-fast-forward)
```

Three distinct problems:

1. **Guaranteed, not a race.** Two machines appending to the same JSONL file
   always conflict on rebase — both add lines at end-of-file.
2. **The status lies.** `src/agi_memory/sync.py` reports `"pull_offline"` for
   what is a merge conflict. The user reads a network blip and ignores it.
3. **Silent permanent divergence.** After the abort, m2 never receives m1's
   memories and can never push its own. No error surfaces.

**Where**: `src/agi_memory/sync.py`, the `sync()` pull/push block.

**Proposed fix**:
- Write a `.gitattributes` into the vault marking `*.jsonl merge=union`, so
  append-only files merge by taking both sides. `union` is a built-in git
  merge driver; no external config needed. This makes the common case
  (both machines appended different records) resolve with no conflict.
- Run the existing vault dedupe after a union merge, since union can
  reintroduce duplicate lines.
- Distinguish failure modes in the status: `pull_offline` (network) vs
  `pull_conflict` (real merge failure) vs `push_rejected`. Never report a
  conflict as an offline condition.
- Surface an unresolved divergence loudly rather than storing it in a status
  field nobody reads.

**Note**: union merge is correct for append-only records. It is NOT correct
for any file where a line is edited in place. Keep the vault append-only, or
this fix stops being safe.

---

## 2. No write-time normalization — DONE (2026-09-13)

**Severity: medium.** The cheaper half of the retrieval problem is untouched.

The caller is always an LLM agent, which writes both the memories and the
queries. There is no human vocabulary gap to bridge — so normalizing terms at
**write** time is a smaller problem than repairing them at **read** time. All
recall work so far (stemming, folding, expansion) has been read-side.

**Evidence**: `memory_record` accepts `text, title, category, project,
supersedes, relations`; only `text` is required. The sole normalization on the
write path is `category.strip().lower()` in `session_layer.record()`.

**Proposed fix**: have the record path (or the tool description the agent
reads) encourage canonical terms and tags — e.g. resolve entity aliases at
write time, so "login" is stored alongside the canonical "authentication".
The alias machinery already exists in L2 (`GraphLayer.add_alias`).

---

## 3. Internal-character typos still miss — DONE (2026-09-13)

"Typos" is not one category. Measured on the real vault (74 observations,
written as real usage, not as test data):

| Typo location | Recall | Why |
|---|---|---|
| Trailing char (`dependencie`) | 73% | porter stemming already collapses it |
| Internal char (`dependncies`) | 10% | stemming cannot touch it |

The synthetic eval reports 11% for internal typos; the real vault says 10%, so
the eval is representative here — this is a real gap, just a narrower one than
"0/19 typos" suggested.

**Fixed** with fragment-coverage matching rather than a trigram index. A
second FTS table would have meant triggers, migrations and another thing to
keep in sync for a case that is by definition rare; the fallback only runs
after every other match failed, so it can afford a bounded scan instead.

Query terms are split into overlapping 4-character fragments; a candidate must
contain at least 50% of them. 0.5 is the knee — 0.45 buys no further recall.

Results: synthetic eval 0% -> 26%; real vault internal-typo recall 10% -> 48%.

**Known cost, accepted deliberately**: about 1 in 7 fallback hits is not the
record the caller meant. These are therefore labelled "[approximate match —
spelling differs]" and scored at 0.4, so an agent cannot mistake one for a
confident recall. Short words (under 5 characters) yield too few fragments and
remain unreachable — inherent, since one deleted character in a 5-letter word
leaves almost nothing to match.

---

## 4. Synonyms — PARTIALLY reached, NOT closed (council, 2026-09-13)

Paraphrase recall is ~6% and no stemming, folding or trigram technique will
move it: `login` -> `authentication` is semantic distance, not surface
distance. Do not attempt to fix this with a looser matcher — that trades
precision for nothing.

Item 2's write-time canonicalization reaches synonyms **only for pairs already
in the alias table**. The council called the earlier "closed" status a paper
close, correctly: an agent writing "auth" when the table only knows "login"
still gets nothing. Coverage of the alias table is the real open question, and
nobody has measured it. Treat this as OPEN with a partial mitigation, not
solved.

**Next step if picked up**: measure alias-table coverage against terms that
actually appear in recorded memories, rather than assuming the table is
populated.

---

## 5. Zero results are silent — DONE (2026-09-13)

Nothing tells the agent (or the user) that a recall found nothing. A tool
whose pitch is "your assistant won't forget" failing quietly manufactures
false confidence: the agent proceeds as though no decision was ever recorded.
Cheap to fix and changes the behaviour of every miss.

---

## 6. The pitch is written in the author's vocabulary — DONE (2026-09-13)

README line 10 still opens with "Zero-dependency, high-performance four-pillar
cognitive memory framework (Epistemic, Semantic, Episodic, Structural Code
Graph)". A stranger has to translate jargon before learning what the tool
does. Suggested framing: "AI coding assistants forget everything between
sessions. This remembers — in 32MB, with no dependencies."

---

## 7. Distribution: it has never been posted — OPEN

0 stars, 0 forks, no external users, no issues, 5 PyPI releases. That is not a
demand signal; nothing has been posted anywhere a user would find it. Every
remaining priority question (what to build, what 1.0 means) is guesswork until
one stranger has used it.

---

## Metric hygiene

**Always state the denominator.** Recall figures in this project mean two
different things and have been conflated:

- **Exact-wording recall: 100%** (6/6 synthetic, 25/25 on the real vault).
- **Degraded-query recall: 30%** — typos, synonyms, word-endings, identifier
  shape. This is the number that improved 7% -> 30%.

Quoting "30% recall" without qualification reads as "fails 70% of the time",
which is false.

**The evals are marked by their own author.** All four layer suites plus
`eval_fuzzy.py` were written by the same person who wrote the code, in the
same week, with no adversarial user. `eval_fuzzy.py` twice reported flattering
numbers that turned out to be measuring corpus leakage; it now has a
probe-hygiene gate that exits non-zero on a leaking probe. Treat 100% scores
as self-consistency, not validation, until an outside user disagrees.

---

## Scope decisions (council-reviewed 2026-09-13)

- **Keep zero-dependency.** It collapses the support surface for a solo
  maintainer (no dependency CVEs, no version matrix). It is NOT a growth
  lever — stop leading with it.
- **Keep the L4 code graph** despite advice to cut it. It is the one component
  no competitor has, it scores 25/25, and it is where zero-dependency actually
  buys something (no LSP daemon, no Tree-sitter binaries). Freeze it rather
  than extend it.
- **Do not chase the enterprise/air-gapped pivot** yet. Interesting, but a
  heavier lift than shipping better search for one unpaid maintainer with zero
  users.

---

## Post-completion council review (2026-09-13)

Reviewed after all items were delivered. Findings:

- **Item 4 was a paper close** — corrected above.
- **The silent-failure class was the real risk**, not the two bugs found. A
  broad `except` around the canonicalization resolver could disable the feature
  again with every eval still passing. Closed with an end-to-end test that
  drives the real MCP path and asserts canonical terms reach the database;
  verified it fails when the original defect is reintroduced.
- **Ship as 0.5.0, not 1.0.** 1.0 is a promise about API and data stability
  that cannot be made with zero external users and self-authored evals.
- **Do not post the launch drafts yet.** Gate them on a clean install performed
  on a machine that is not the maintainer's, and on two real machines syncing.
  Posting first converts a launch into a bug-report flood a solo maintainer
  cannot triage.
- **Stop optimizing recall.** 100% exact / 35% degraded is enough; further
  tuning is diminishing returns against getting any external user.
- **The self-grading discount still applies** and does not appear anywhere in
  the reported numbers. Every eval was authored by the code's author.

---

## 8. Hard delete only deleted L1 — FIXED (2026-09-13, reported externally)

**First bug report from someone other than the maintainer.** They asked whether
`agi-memory delete <id> --hard` being L1-only was intentional. It was not, and
checking made it worse than reported:

1. `delete_observation(hard=True)` was a single `DELETE FROM observations`.
2. Promotion copied `project, title, facts, concepts` and **not** the
   observation id, so a promoted fact had no link back to its source — a
   cascade was not merely unimplemented, it was inexpressible.
3. The vault is append-only, so a hard-deleted record survived there and was
   restored by the next `import_from_vault` or sync from another machine.

So "hard delete" meant "delete from the L1 index" — wrong for anyone deleting
something they need gone.

**Fixed**: `graph_edges` gains a `source_ref` column (migrated in place) that
records which observation promoted a fact; promotion carries `obs:<id>`;
`GraphLayer.delete_by_source()` purges them; and the vault gained tombstones —
themselves appends, so deletion propagates across machines like any other
record. Import and export both honour them.

`promote()` falls back to the older `add(text)` signature on TypeError, so a
third-party L2 keeps working without cascade support.

Verified end to end: after a hard delete and a vault re-import, the L1 row,
the promoted facts and search results are all gone.

**Still open**: a soft delete does not touch promoted facts, which is arguably
correct (it marks superseded rather than removing) but is undocumented. And
tombstones are keyed on content_hash, so an identical memory recorded later
gets the same guid and would be suppressed. Worth revisiting if anyone hits it.
