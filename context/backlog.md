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

**Measured (2026-09-14, `tests/alias_coverage.py`)** against the real vault on
the maintainer's machine — 16,373 distinct terms across 712,691 occurrences:

| | covered by the alias table |
|---|---|
| distinct terms | 14 / 16,373 = **0.1%** |
| weighted by frequency | 3,933 / 712,691 = **0.6%** |

The 14 are exactly the entries in `STANDARD_ALIASES`. **Nothing has ever been
added to the table in real use**, so the write-time canonicalization booked as
item 2's mitigation is, in practice, inert: it fires only on `fcm`, `k8s`,
`jwt`, `sqlite`, `postgres`, `auth`, `ts`, `py`, `mcp`, `db`, `api`, `ui`, `ci`
and `postgresql`.

**Read the number carefully.** It is not "99.9% of queries fail" — most terms
have no synonym and need no alias entry. What it establishes is narrower and
still damning: the table is seed-only. Frequent, obviously aliasable terms in
this corpus (`flutter`/`dart`, `widget`/`screen`, `theme`/`brand`,
`configuration`/`config`, `migration`) have no entry, and no mechanism exists
that would ever create one.

**Consequence for item 2**: it should not be read as having closed anything for
synonyms. The mechanism works; the data behind it is empty.

**Next step if picked up**: the gap is population, not machinery. Either mine
alias candidates from the corpus (co-occurring terms that never appear in the
same memory are a poor signal; terms an agent used interchangeably across
sessions are a better one) or accept that the table only ever holds what a
human curates, and say so in the README rather than implying synonym support.

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

---

## 9. Abandoned sessions come back as open tasks — FIXED (2026-09-14)

**Severity: high.** Named by a commenter as "context poisoning", and they were
right; nothing in the design addresses it.

Scenario: a design session produces several rejected approaches, the user
corrects the model repeatedly, and eventually drops the task. The next session
starts fresh, is handed last-session context, and assumes the task is both
still open and the thing to work on.

**Verified**: `episodic_sessions.status` only takes `active` or `completed`.
`end_session()` sets `completed` regardless of how it went, and the
session-start hook injects "Last Session: <goal> -> <summary>". An abandoned
session is therefore indistinguishable from a finished one, and reads as an
open task with a running start.

The failure generalises: we store *what happened* and never *how it ended*.
A rejected design, a reverted change and a shipped feature all recap the same.

**Fixed**: `episodic_sessions` gained an `outcome` column (completed /
abandoned / blocked / superseded / unknown, defaulting to `unknown`), a
`set_outcome()` separate from `end_session()` because the caller who knows how
the work went is not the lifecycle hook that ends it, and recap/timeline
rendering that leads with the outcome and refuses to present anything unmarked
as continuable. Exposed as `memory_session_outcome` and `agi-memory outcome`.

**Residual**: until agents actually call it, every session reads `unknown`,
which is honest but noisy. The memory-discipline rules now ask for the call.
Worth checking after a week of real use whether agents comply; if they do not,
the warning becomes wallpaper and needs rethinking rather than louder wording.

---

## 10. projectmem is a direct competitor — POSITIONING, not a defect

https://github.com/riponcm/projectmem — 822 stars, Python, MIT.

Same core bet: local-first, no embeddings, no vector database, append-only
JSONL event log, MCP server, aimed at coding agents remembering decisions,
covering Claude Code / Cursor / Codex / Antigravity.

| | projectmem | agi-memory |
|---|---|---|
| Dependencies | Typer, watchdog, D3 | stdlib + SQLite only |
| Search | plain-text over files | SQLite FTS5 |
| Scope | per-repo `.projectmem/` | global vault, cross-project |
| Cross-machine | not offered | git sync with union merge |
| Code graph | `structure.json` | AST callers / dependencies / blast radius |
| Assistants | 5 | 13 |
| Adoption | 822 stars | 0 |

**What they do better, worth learning from:**
- Their pitch names the failure ("warns agents before repeating failed
  approaches") rather than the category ("persistent memory").
- They separate intent (`plan.md`) from memory (`events.jsonl`). We conflate
  them, which is arguably why item 9 exists.
- A pre-commit gate and file watcher accrue memory without the agent choosing
  to record.

**Implication**: stop implying nobody is doing this. The honest positioning is
zero-dependency, multi-machine, plus the code graph. Someone already using
projectmem has little reason to switch, so the audience is people who have
found neither.

---

## 11. Decisions arrive as settled context, with no rationale — PARTIALLY FIXED (2026-09-14)

Raised by a commenter running a multi-role Claude Code setup: carrying
decisions forward is useful right up until the decision was wrong. After that
every later session inherits it and none re-examine it, because it arrives as
settled context rather than as something somebody argued for.

**What exists** (verified, and better than first assumed):
- `supersedes` links a decision to the one it overrides.
- A superseded record is rendered with a `[SUPERSEDED]` marker in recall, so a
  reader can at least see it is dead.
- L2 edges are bi-temporal (`is_active`, `valid_from`, `valid_until`,
  `superseded_by`), so a fact can be invalidated rather than deleted.
- Recording something similar to an existing memory returns the conflicts, so
  an agent can see it is contradicting itself.

**What does not exist:**
- **No rationale field.** `memory_record` takes text, title, category,
  supersedes, relations. The "why" survives only if the agent happens to write
  it into the prose, and nothing asks it to. Usually absent.
- **No forward pointer.** `observations` has no `superseded_by` column — only
  `type` flips to `superseded`. A reader sees "this is dead" and has no way to
  reach what replaced it. The L2 edge table has this; L1 does not.
- **No confidence or constraint capture.** Nothing records what a decision
  depended on, so nothing can flag when those conditions no longer hold.

**The deeper problem, which a field would not fix**: even with a rationale
stored, it returns as prose in a retrieved block, indistinguishable in tone
from a fact. Nothing marks "argued for under these constraints, which may no
longer hold". A wrong decision with good reasoning attached still reads as
settled. Same root cause as item 9 — outcomes and status are not part of how
memory is presented, only of how it is stored.

**Done (2026-09-14)**, both of the cheap steps:
- `observations.superseded_by` (migrated in place) and recall now renders
  `[SUPERSEDED by #N]`, so a dead decision names its replacement instead of
  only announcing that it is dead.
- `rationale` on `memory_record` and `SessionLayer.record()`: its own column,
  also appended to `facts` so FTS can reach it, rendered as `Why: ...` in
  recall and `Why:` in `agi-memory inspect`, and carried through the vault so
  it survives the machine boundary. Asked for in the memory-discipline rules.

**Still open, and it is the harder half**: a stored rationale still returns as
prose in a retrieved block. Nothing marks it as "argued for under constraints
that may no longer hold", and nothing records what those constraints were, so a
wrong decision with good reasoning attached still reads as settled. Confidence
and constraint capture remain unbuilt. Also unbuilt: supersession does not
survive a vault import on a second machine, because `superseded_by` holds a
local row id — the marker text carries over, the link does not.

**Correction to make if this thread continues**: I told the commenter
supersession was not surfaced. It partly is — the `[SUPERSEDED]` marker exists.
What is missing is the pointer to the replacement and the rationale.
