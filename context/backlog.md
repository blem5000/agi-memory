# Backlog & Open Findings

Durable record of known defects, deferred work, and the reasoning behind
decisions that are easy to re-litigate. Each item states the evidence, so a
future session can act without re-deriving it.

Last reviewed: 2026-09-14 (post-0.6.0 backlog sweep).

## Standing gates — why the remaining open items are not being worked

Nothing below is open for lack of time. Each is blocked on something that must
happen outside the code, and picking any of them up before its gate is met
would mean building on a guess. Stated here so a future session stops
re-deriving it.

| Item | Gate | Who or what clears it |
| :--- | :--- | :--- |
| 7. Distribution | ~~Nobody outside the author has used this~~ — **posted to Reddit 2026-09-14**. Now waiting on the first issue, question or install report from a stranger, which is the evidence item 11 needs. | Done; watching. |
| 14. Static embeddings | ~~Measure first~~ — **measured 2026-09-14 and closed**. Paraphrase recall went 0/18 to 1/6 with 500 real distractors, for 89 MB of Rust and C dependencies plus a 307 MB model cache. The number did not move; the item died, as its own gate said it would. | Done. |
| 15. Usage failure, remaining half | Measuring whether a model *used* a memory correctly needs a model in the loop — a network call and a dependency. `eval_usage.py` measures the deterministic floor and says so. | A separate opt-in harness, or accepting the proxy. |
| 11. Contextual applicability | **Reframed 2026-09-14**: not a modelling problem. In a real 14,748-record vault the rationale field has been used zero times by real work and supersession three times, and only 5.3% of records pass through the tool that could ask. The gap is adoption, and the advisory notice this project already ships converts at ~0%. | Measure on one assistant whether a required field produces reasoning or filler. Not gated on item 7 any more. |

Item 11 no longer waits on item 7. Profiling a real vault on 2026-09-14
answered its question directly: the fields it wants to improve are not being
written at all, so the work is adoption rather than modelling. Item 14 was
measured the same day and closed. What item 7 still buys is item 15 — whether a
model *uses* a memory correctly is not answerable from one person's store.

The pattern across items 4, 11, 14 and 16 is worth stating once: **every time a
number was put on one of these, the answer changed.** The alias table was a
paper close at 0.1% coverage; static embeddings looked promising at 4/6 and were
chance; the rationale field looked shipped and has never been used. Measure
before building is not a slogan in this file, it is the only thing that has
worked. That ordering is
the point: distribution is not a nice-to-have at the end of the list, it is
what makes the rest of the list decidable.

---

## 1. Vault git-sync silently diverges on concurrent machines — FIXED (verified 2026-09-14)

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

**Status**: all three parts were implemented and the item was simply never
re-labelled. `sync.py` writes the `merge=union` gitattributes at init,
`ensure_merge_attributes()` repairs an existing vault, and the statuses are now
distinct (`pull_conflict` / `pull_offline` / `push_rejected`).
`tests/multi_machine_test.py` drives two isolated HOMEs against a shared bare
repo through the real CLI and passes 11/11, including the case that used to
lose data: both machines record before either syncs. A third machine cloning
fresh sees all three memories.

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

## 4. Synonyms — CLOSED as far as it honestly can be (2026-09-14)

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

**Done (2026-09-14): the second branch, deliberately.** Mining was not built —
the better signal named above (terms an agent used interchangeably across
sessions) needs the miss log from the council plan, which does not exist, and
guessing pairs from co-occurrence would populate the table with noise that
silently rewrites queries. So the table stays curated, and the two things that
made "curated" a fiction are fixed:

- **There was no way to curate it.** `add_alias` existed only in the Python
  API, which is why the table had never gained an entry in real use. There is
  now `agi-memory alias list | add <term> <canonical> [--category C] | rm
  <term>`. `remove_alias` is new: a wrong entry rewrites every term it matches
  at both write and query time, so a table you can only add to is a trap.
  Covered in `test_offline.py`, including the lowercase match and the cache
  eviction.
- **The docs implied it was automatic.** `docs/pillars.md` and
  `rules/architecture.md` sold "synonym canonicalization" without saying the
  table holds 14 seed entries and learns nothing. Both now state the 0.1%
  measurement and point at the CLI. `README.md` never made the claim.

**What remains true and is not a defect to fix here**: paraphrase recall stays
at ~6% for anything outside the table, and no keyword technique moves it. That
is item 14's subject, and it is gated on a measurement nobody has run.

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

## 7. Distribution: it has never been posted — POSTED (2026-09-14), now waiting on signal

0 stars, 0 forks, no external users, no issues, 5 PyPI releases. That is not a
demand signal; nothing has been posted anywhere a user would find it. Every
remaining priority question (what to build, what 1.0 means) is guesswork until
one stranger has used it.

**Posted to Reddit, 2026-09-14.** The gate is cleared: the project is now
somewhere a stranger can find it, and the comment threads have already produced
four backlog items (11, 14, 15, 16) — one of which, 14, was measured and killed
on the evidence.

**State at the moment of posting**, so later numbers mean something: 4 stars,
1 fork, 0 issues, 0 watchers, 6 PyPI releases (0.6.0).

**What to actually watch for**, in rough order of how much it should change
plans:
1. **An issue or a question from someone who installed it.** The first one is
   worth more than any star count — it is the first evidence of a real use.
2. **Which pillar people ask about.** The build order after this should follow
   what strangers care about, not what is next in this file.
3. **Where it breaks on a machine that is not this one.** Every install path
   here has been exercised by its author.

**What not to read into it**: stars are not usage, and an upvote is not a user.
Do not let a good thread reopen item 14 or start a trust framework (item 16)
without the measurement each of those entries asks for.

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

**Also done (2026-09-14): supersession now survives the machine boundary.**
`superseded_by` holds a row id, which is local, so a second machine importing
the same memories saw the replacement arrive while the record it replaced still
had no pointer to it. Records now carry `supersedes_refs` — the content hashes
of what they superseded, which are stable across machines — and
`import_from_vault` resolves those to local ids and rebuilds the chain. The
export path was also dropping `rationale` entirely, because
`export_dirty_to_vault` selects a fixed column list that had not been updated;
both columns now travel. Covered by a test that exports from one database,
imports into another, and asserts the chain and the rationale both survive;
verified to fail when the re-link is removed.

**REFRAMED 2026-09-14 on evidence from a real 14,748-record vault.** The
remaining half was written up as a presentation and modelling problem. It is
not. It is an adoption problem, and the numbers are not close:

| | count | share |
| :--- | ---: | ---: |
| observations total | 14,748 | |
| written through `memory_record` (the only path that accepts a rationale) | 785 | **5.3%** |
| carrying a rationale | 6 | 0.04% |
| ...of those, written by a test rather than by real work | 6 | **all of them** |
| superseded records | 3 | 0.02% |

So in real use the rationale field has been used **zero** times, and
supersession three times in fourteen thousand. Nothing marks a decision as
conditional because nothing marks decisions at all. Improving how a rationale
*renders* optimises a path that carries no traffic.

Two further things that number exposes:

- **94.7% of the corpus never passes through the tool that could ask for any of
  this.** Those records arrived by import and bulk paths, and they are mostly
  `discovery` (46% of the whole store), not decisions. A model built around
  decisions and their supersession is being applied to a store that is largely
  observations.
- **The steering mechanism this project already ships converts at roughly
  zero.** `memory_record` returns a `[Notice - Potential Overlap Found]` when a
  new memory collides with an existing one, explicitly so the agent can resolve
  it with `supersedes`. Three superseded records in 14,748 is the outcome of
  that notice. Proposing a second advisory notice — "you did not give a
  rationale" — would be building the same thing that measurably does not work.

**What is actually left**, in order of honesty rather than appeal:

1. **Make it structural, not advisory.** A `rationale` that is `required` in
   the tool schema when `category` is `decision` is the only intervention here
   that does not depend on an agent choosing to be diligent. It is also a
   breaking change to the tool contract, and it will produce filler rationales
   from agents that have nothing to say. Worth measuring on one assistant
   before it ships to thirteen.
2. **Say so.** If the field stays optional and unused, the README and docs
   should not imply that decisions carry their reasoning. Same correction as
   item 4's alias table: the mechanism exists, the data behind it does not.
3. **Question the model.** If 46% of what people store is `discovery`, the
   valuable distinction may not be "which decision replaced which" at all.
   That is worth knowing before more is built on the decision model.

Do not start (1) without the measurement in (3). The old framing — confidence
and constraint capture — stays parked; it is a refinement of a mechanism that
has not yet been used once.

**Correction to make if this thread continues**: I told the commenter
supersession was not surfaced. It partly is — the `[SUPERSEDED]` marker exists.
What is missing is the pointer to the replacement and the rationale.

---

## 12. Destructive operations have no confirmation gate — DELIVERED (2026-09-14)

The maintainer of HOL Guard offered to add an agi-memory extension that would
checkpoint `delete --hard`, `pin` and `unpin` while leaving `log`, `inspect`,
`recall` and `blocks` automatic — a stop before an agent deletes or rewrites
persistent memory, without slowing reads down.

The split is right, and their list is missing the most dangerous operation.
**`memory_sync` with `action=dedupe` rewrites the canonical append-only vault
in place** and has already destroyed data once: the semantic dedupe keyed on a
truncated 120-character prefix collapsed five distinct observations into one.
It belongs above `delete --hard`.

Also missing from their list: `memory_record` with `supersedes` (flips an
existing record's type), and `memory_bootstrap` (bulk-writes from git history
into a possibly non-empty store).

**Checkpoint**: `memory_sync(dedupe)`, `delete --hard`, `memory_pin`,
`memory_unpin`, `memory_record(supersedes=...)`, `memory_bootstrap`.
**Automatic**: every read, plus plain `memory_record`, `memory_promote` and
`code_index` — all additive.

**Done (2026-09-14)**: every tool now carries MCP `annotations` with
`readOnlyHint` and `destructiveHint`, travelling with `tools/list`, and a test
fails if a tool is added without a classification. `memory_sync`, `memory_pin`,
`memory_unpin` and `memory_bootstrap` are marked destructive.

**Known limit**: annotations have no argument granularity. `memory_record` is
marked additive despite `supersedes` mutating an existing record, because
marking the most frequent write in the system destructive would put a prompt in
front of every memory an agent saves, and agents would stop saving. Its
description says a gate should key on the argument instead. Same shape applies
to `memory_sync`, which is marked destructive on account of `action=dedupe`
even though `action=sync` and `action=status` are harmless.

**Done (2026-09-14)**: the extension is written and open as a draft PR against
hashgraph-online/hol-guard (#2921) — `command.agi-memory`, external and opt-in,
six reviewed operations at the CLI boundary: `sync dedupe`, `sync init`,
`delete --hard`, `pin`, `unpin`, `bootstrap`. `sync status`, `log`, `inspect`,
`blocks`, `outcome`, `recall`, `timeline` and the code-graph queries stay
automatic.

Two things that only surfaced by reading our own CLI rather than its help text,
both of which would have left the gate bypassable:

- `agent-memory` is an exact alias of `agi-memory`, and `agent-bootstrap` of
  `agi-bootstrap`. All six console scripts ship in every install, so a matcher
  naming one name is bypassed by typing the other.
- `sync` dispatches on a literal positional. Bare `agi-memory sync` does not
  reach the sync module at all — it falls through to the installer — so
  prefix-matching `sync` gates the wrong program.

**Still open**: maintainer review of that PR, and argument-level MCP gating,
which is Guard-side work.

---

## 13. Dedupe merging distinct memories — ALREADY FIXED, verified 2026-09-14

Opened while reviewing item 12, then closed by reading the code rather than
assuming the incident still stood. `deduplicate_and_compact` in
`src/agi_memory/vault.py` hashes the **full** normalized text into the semantic
key, with a comment saying why a prefix is unsafe, and
`t_compaction_preserves_distinct` in `tests/chaos_test.py` already feeds it five
observations sharing a long preamble with different endings and asserts all five
survive, alongside three true duplicates that must collapse to one.

Recorded here because item 12 cites the original incident: the operation is
still the most destructive one in the system and still deserves a confirmation
gate, but the specific defect that caused the data loss is gone and tested.

---

## 14. Static embeddings could close the synonym gap without the 500MB — MEASURED, NOT WORTH BUILDING (2026-09-14)

Raised by a commenter pointing at [Model2Vec / potion](https://huggingface.co/collections/minishlab/potion)
and the [semble](https://github.com/MinishLab/semble) code-search MCP built on it.

**Why this one matters more than the usual "just use embeddings" reply.** It
attacks the premise rather than the tradeoff. Potion models are *static*
embeddings: a token to vector lookup table distilled from a sentence
transformer, so inference is tokenize and mean-pool, with no forward pass and
no torch. Tens of MB, CPU-only. The "500MB and 200-500ms" argument this project
leans on does not apply to them, and repeating it against this suggestion would
be dishonest.

It also targets exactly the measured gap. Item 4 established that synonym
recall is ~6% and that the alias table covers 0.1% of the real vocabulary.
Semantic similarity is the only thing that closes that.

**What would actually have to be solved** (in order of difficulty, not order of
mention):

1. **The tokenizer is the dependency, not the model.** Model2Vec uses the
   HuggingFace `tokenizers` package, which is Rust. Zero-dependency means
   reimplementing the tokenizer over the shipped `tokenizer.json` in pure
   Python. This is the real work; everything else is arithmetic.
2. **The math is free.** Cosine over a few thousand vectors of a few hundred
   dimensions is milliseconds in pure Python. Not a constraint. Storage of the
   vectors in SQLite is a blob column, also not a constraint.
3. **Distribution is the actual decision.** A 8-32MB model either bloats the
   wheel or needs a first-run download, and a download breaks the offline
   guarantee that is a stated property of this project. Neither is obviously
   right.
4. **Licensing and provenance** of a shipped model file, which this project has
   never had to think about.

**Proposed shape if picked up**: `pip install agi-memory[semantic]`. BM25 stays
the zero-dependency default and the offline guarantee holds for it; semantic
recall is opt-in, and its absence degrades to today's behaviour rather than
failing. That keeps the differentiator honest instead of quietly abandoning it.

**Do not start with the integration.** Start by measuring whether it is worth
it: embed the existing vault with potion, run `tests/eval_fuzzy.py`'s synonym
category against it, and compare with the 6% baseline. If it does not move that
number substantially on this corpus, none of the work above is justified.

**Also worth reading regardless**: semble, for how it handles chunking and
storage for code search.

---

**Measured (2026-09-14).** The gate above said measure before building. Done,
out of tree in a throwaway venv, against `eval_fuzzy.py`'s own corpus and
probes so the numbers are comparable to the 0/18 paraphrase baseline.

**The first run looked promising and was wrong.** On the bare 6-document
fixture, `potion-base-8M` scored paraphrase 4/6 at top-3. With a 6-document
corpus, top-3 hits 50% by luck alone, so that number meant nothing. Re-running
with the fixture buried in **500 real vault observations** (chance at top-3:
0.59%) is the honest test:

| top-5, 506 docs | potion-base-8M | potion-retrieval-32M | BM25 today |
| :--- | :--- | :--- | :--- |
| paraphrase | 0/6 | **1/6** | 0/18 |
| abbreviation | 0/2 | 1/2 | 1/6 |
| typo | 3/6 | 3/6 | 5/19 |
| precision (exact query ranks its own record first) | 6/6 | 6/6 | 6/6 |

Both models miss `login` -> `authentication`, which is the canonical example
this whole line of work exists to fix. The retrieval-tuned model finds one
paraphrase out of six. That is not the step change the suggestion promised, and
it is nowhere near enough to justify the costs below.

**What it would have cost**: `tokenizers` is Rust, `numpy` is C — the venv came
to **89 MB** plus a **307 MB** HuggingFace cache, against a stated
zero-dependency, offline guarantee. Reimplementing the tokenizer in pure Python
was already known to be the real work; the measurement says the payoff on the
other side of it is one probe.

**What the numbers do say**: embedding is genuinely fast (0.06 ms/doc, 0.04 ms
per query encode) and precision held at 6/6 — it does not wreck exact matching.
So the idea is sound and the implementation is cheap; the *semantics at this
model size* are the thing that does not deliver. A full sentence-transformer
might. That is the 500 MB this project exists to avoid.

**Status**: closed unless someone brings a measurement showing a bigger static
model clears this bar. The scripts are gone with the scratchpad, but they are
thirty lines: embed the corpus, cosine, score the same probe table.

---

## 15. Evals measure retrieval, never whether the memory was used correctly — PARTIALLY CLOSED (2026-09-14)

Named by a commenter writing about persistent-memory architecture: *separate
retrieval failure from usage failure. Sometimes the right memory was found, but
the model used it incorrectly.*

Every number this project reports is a retrieval number. `eval_l1` through
`eval_l4`, `eval_fuzzy`, the 100% exact-wording and 35% degraded figures — all
of them ask "did the right record come back". None ask "did the agent then act
on it". That is half the pipeline, unmeasured, and the headline numbers do not
say so.

This matters more here than for a search engine, because the consumer is an
agent that will act. A recall that returns the right memory and is then ignored
or misread fails the user identically to a recall that returned nothing, and
today the two are indistinguishable in every metric.

**Why it is tractable**: it is an eval-design problem, not an architecture one.
No storage or ranking change is required to start measuring it.

**Proposed first step**: extend the fuzzy eval's probe format with an expected
*behaviour*, not only an expected record — a memory saying "we rejected
Postgres" should make a subsequent question about datastore choice answer
"Postgres was rejected", not merely retrieve the record. Score retrieval and
use separately, and report them as two numbers, because collapsing them is the
thing that hides the failure.

**Done (2026-09-14)**: `tests/eval_usage.py` scores retrieval and
**actionability** as two separate numbers. Actionability asks whether the block
handed to the agent carries the qualifier needed to act on it correctly — a
superseded decision that names its replacement, a constraint that carries its
reason, a fuzzy hit that admits it is approximate, a recap that refuses to
present abandoned work as continuable. Currently 5/5 and 2/2.

Verified sensitive rather than self-confirming: removing the rationale
rendering, the supersession pointer and the do-not-resume warning drops
actionability to 2/5 **while retrieval stays at 5/5**. That is the thesis
demonstrated — three memories still found, none safely usable, and every other
eval in the repository would have reported a clean sweep.

**Still open, and it is the part that needs a model**: this measures whether
correct use is *possible*, not whether a model then used it correctly. Closing
that needs an LLM in the loop, which means a network call and a dependency, so
it cannot live in this test suite as it stands. The honest options are a
separate opt-in harness or accepting the proxy. The proxy is a floor, not the
measurement the commenter was describing, and the eval's own output says so.

**Related**: item 11's remaining half. A rationale that returns as
indistinguishable prose is a usage failure waiting to happen — the memory
arrives, the agent cannot tell it was conditional, and acts on it anyway.

---

## 16. Nothing records whether a source is authoritative — PARTIALLY CLOSED (2026-09-14)

From the same comment: relevance, temporal validity, authority validity and
contextual applicability are four different questions, and this project only
answers the first properly.

- **Relevance** — BM25, stemming, fragment matching. Every improvement made
  this week went here.
- **Temporal validity** — partial. L2 edges are bi-temporal (`valid_from`,
  `valid_until`, `is_active`); L1 observations have nothing equivalent beyond
  the superseded flag.
- **Authority** — absent. Nothing records whether a memory is a trusted source
  for the question being asked. A guess an agent wrote while exploring and a
  decision the user confirmed are stored identically and rank identically.
- **Contextual applicability** — absent, and the same gap as item 11: nothing
  records what a decision depended on, so nothing can flag when those
  conditions stop holding.

**The uncomfortable version**: the whole ranking stack is a relevance engine,
and relevance is the one dimension that was already adequate. A memory can rank
first, be exactly on topic, and be wrong for the current question.

**Cheapest useful step**, if picked up: an explicit origin on each observation —
user-confirmed, agent-inferred, or bootstrapped from git history — set at write
time, surfaced in recall, and used to break ties. That is a much smaller change
than a trust model, and it separates "the user told me this" from "an agent
guessed this while exploring", which is the distinction that actually bites.

**Do not** build a general trust framework off the back of a comment. Measure
first whether misranked-but-relevant memories are actually causing bad agent
behaviour — item 15's eval would be the instrument for that.

**Reframed 2026-09-14, same evidence as item 11.** `origin` ships, and it will
be filled about as often as `rationale` is — which is never — unless something
other than a tool description asks for it. The one difference worth protecting:
`bootstrap.py` sets `origin="bootstrapped"` itself, with no agent involved, and
that is 61 of the 81 origins now in the vault. **The origins that get set are
the ones a code path sets, not the ones a model is asked to set.**

That is the design rule to carry forward for the rest of this item. Authority is
worth recording only where a code path can determine it without cooperation:
bootstrap output, vault imports, and `memory_pin` (a pinned block is
user-curated by construction). An `origin` an agent must volunteer honestly is
the same bet as `rationale`, and that bet has already lost 785 times.

**Done (2026-09-14): the cheapest step above, and only that.** `observations.origin`
(migrated in place) holds `user-confirmed`, `agent-inferred` or `bootstrapped`,
set at write time, defaulting to `agent-inferred`. An unrecognised value falls
back to the default rather than becoming a trust claim, since the field is only
worth anything if it cannot be inflated by accident.

- Recall labels the two origins that change how a reader should treat the
  memory: `[confirmed by the user]` and `[bootstrapped from git history,
  unverified]`. `agent-inferred` is the common case and is left unmarked, so
  the label carries signal instead of decorating every line.
- `bootstrap.py` now writes `bootstrapped`, which is where the distinction
  actually bites: a line lifted out of a commit message is a description of
  what the code did once, and it was previously indistinguishable from a
  decision somebody stood behind.
- Ranking uses origin as the **last** sort key, after BM25 rank. It separates
  records the scorer could not, and never reorders on authority over relevance.
- Carried through the vault, so the distinction survives the machine boundary —
  the same bug class that dropped `rationale` on export in item 11.
- `eval_usage.py` gained a probe asserting a bootstrapped memory announces
  itself; verified to fail when the label is removed. Now 6/6 and 2/2.

**Still open**: temporal validity on L1 and contextual applicability, which is
item 11's remaining half. Nothing records what a decision depended on, so
nothing can flag when those conditions stop holding. Origin says who wrote a
memory, not whether it still applies — and the measurement this item called for
(whether misranked-but-relevant memories actually cause bad agent behaviour)
has still not been run, so any further trust modelling remains unjustified.

---

## 17. Running the tests wrote into the developer's real vault — FIXED (2026-09-14)

**Severity: high.** Test fixtures reached a production memory store and were
pushed to its git remote.

`SessionLayer.record` and `GraphLayer.add_edge` dispatch to module-level
listeners, and `vault.py` and `sync.py` register theirs on import. Those
listeners append to the **configured** vault and schedule a git sync — they
took no notice of which database the write was actually aimed at. So every test
that pointed a layer at a temporary file still wrote its fixtures into the real
vault, and auto-sync then committed and pushed them.

**Measured on the maintainer's own machine**: 227 records across both the
SQLite index and `observations.jsonl`, under projects named `p` (214), `usage`,
`x`, `mod-proj`, `hop`, `p-render`. Titles like "Queue", "W" and "Key Rotation"
— eval fixtures and throwaway probes, indistinguishable from real memories once
they land.

**Fix**: every dispatched payload now carries `db_path`, and the vault and sync
listeners ignore anything that is not the default database. The scoping lives
in those two listeners rather than in the dispatcher, because the dispatcher's
contract — a registered listener hears every record — is a documented extension
point with a test asserting it. A payload without `db_path` is treated as the
default, preserving the old behaviour for any caller building one by hand.

Guarded in `test_offline.py` with a canary: write to a temp database, assert the
real vault's files did not grow and the canary is absent. Verified sensitive by
removing the scoping and watching it fail.

**Decided 2026-09-14: the 227 records stay.** The maintainer's call — nothing is
discarded. They are indistinguishable from real memories only in shape, not in
consequence: they sit under project names (`p`, `usage`, `x`, `mod-proj`, `hop`,
`p-render`, `p-leakcheck`) that no real work uses, so project-scoped recall
never surfaces them, and the vault is append-only by design. A later session
must not "tidy" them: deleting from an append-only store means tombstones that
propagate to every machine, which is a larger and more permanent act than the
mess it cleans. They are also now the only real-world sample of what the leak
looked like, which is worth keeping while item 17's fix is young.

**The wider lesson**: ambient module-level listeners that act on global config
are invisible at the call site. Nothing in a test that says
`SessionLayer(db_path=tmp)` suggests it is also writing to `~/.agi-memory` and
pushing to GitHub. Treat any new global listener as suspect for the same reason.

---

## 18. The identifier row was one probe; constants were not indexed at all — FIXED (2026-09-14)

Raised by a reader of the posted eval: *"how much does the code graph recover
when wording changes but symbol names or file paths stay stable — is that
category broken out?"*

It was broken out, and it was **1/1**. One probe (`getUserById` vs
`get_user_by_id`) sitting in a table beside categories with sixteen to nineteen.
A passing test presented as a measurement.

**Widened to 15 probes** across the shapes that actually occur: camelCase,
PascalCase, kebab, flattened, SCREAMING_SNAKE against both camel and snake, a
member path (`AuthTokenStore.rotateSigningKey`), and a class name queried in
snake. Result: **14/15 (93%)** — the claim survived, which is the only reason
it is worth quoting now.

The two things it exposed are worth more than the number:

1. **Module-level constants were never indexed.** `MAX_RETRY_COUNT = 5` created
   no symbol, so `code_callers` on it returned nothing and `code_impact`
   reported no blast radius — for precisely the kind of shared value (a
   timeout, a limit, a feature flag) whose blast radius is the reason anyone
   asks. Now indexed as `kind='constant'` (uppercase names at module scope
   only, so locals stay out), and referencing one emits an edge, since a
   constant is referenced rather than called and the `ast.Call` walk could
   never see it.
2. **A member path does not resolve.** `AuthTokenStore.rotateSigningKey` misses
   where `rotateSigningKey` hits. That is the 1 in 14/15 and it is left open:
   `qualified_name` is stored but not consulted by the identifier fallback.

**Also corrected**: the fixture declared the constant without referring to it,
so even after indexing, its probe measured nothing — `get_callers` traverses
CALLS/IMPORTS/EXTENDS/IMPLEMENTS, and a symbol nothing refers to has no callers.

**Numbers now** (was 20/60 = 33%): morphological 13/19, typo 5/22, identifier
14/15, abbreviation 1/6, paraphrase 1/18. **Overall 34/80 = 42%.** The rise is
mostly the identifier category gaining weight, not the matcher improving — say
that when quoting it.

**Unexplained, flagged rather than buried**: L3 paraphrase reads 1/6 where an
earlier run today read 0/6, stable across three consecutive runs since. Not
isolated. L4 morphological and typo are 0/4 each now rather than 0/1 — the same
failure, better sampled.
