# agi-memory

> **Active.** Day-1 history import is built in: `agi-memory history-import` reads
> the session transcripts Claude Code, Codex and OpenCode already wrote to disk
> into L1 observations, so recall works from moment zero instead of an empty
> vault. Zero dependencies, no LLM — just the history you already have.

[![CI](https://github.com/kdbhalala/agi-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/kdbhalala/agi-memory/actions)
[![PyPI](https://img.shields.io/pypi/v/agi-memory.svg)](https://pypi.org/project/agi-memory/)

Coding assistants forget everything when a session ends. agi-memory is a small
local memory they can all read and write, so you don't have to re-explain your
project every time you open a new session or switch tools.

## A basic example

On Monday you tell Claude Code why webhook retries are capped, and it saves that:

```
memory_record(
  title="Webhook retry limit",
  text="Payment webhooks retry at most 5 times with exponential backoff. "
       "Do not raise the limit: the provider bans endpoints that retry more.",
  rationale="Stripe disables endpoints after repeated failed retries",
)
```

On Thursday you're in Cursor, in a fresh session, and ask it to make webhooks
more reliable. Before touching the code it checks memory:

```
$ agi-memory recall "webhook retries" --project shop
#1 [shop] Webhook retry limit: Payment webhooks retry at most 5 times with
exponential backoff. Do not raise the limit: the provider bans endpoints that
retry more. | Why: Stripe disables endpoints after repeated failed retries
```

So it doesn't "fix" reliability by raising the retry count. That's the whole
idea: decisions, bugs you already fixed, and what you tried last time stay
available across sessions and across tools.

## How it works

- Memories are stored in SQLite on your machine, and also written to plain
  append-only text files you can read, diff, and keep in git.
- Each assistant talks to it through a local MCP server. It works in Claude
  Code, Cursor, Windsurf, Codex, OpenCode, Antigravity, Aider, Goose, Cline,
  Roo Code, Crush, Pi, and Hermes Agent.
- Nothing leaves your machine unless you point the memory files at a git
  remote to sync them between computers.
- It's pure Python with no dependencies: no vector database, no model
  download, no background service.

Besides notes and decisions, it also keeps a short history of past sessions and
an index of your code (functions and who calls them), so an assistant can ask
"what calls this?" before changing it.

**Read the code index as a fast first pass, not as an LSP.** Python is parsed
with `ast`; JavaScript, TypeScript, Go, Rust and Dart are read with a
per-language line scanner. It is fast because it is shallow, and the
consequences are concrete: a symbol inside a string literal, a line commented
out mid-file, or a call inside a nested closure can be missed or attributed to
the wrong enclosing function. A missed edge reads as "no callers" — the same
answer a real absence gives. Before a delete, confirm against the file or your
editor's own symbol search. It covers ten extensions across six languages.

## What it won't do

Search is by keyword, not meaning. If you saved "authentication" and later ask
about "login", it can miss. It helps to use the words you'd search for when
saving something. The measured hit rates, including the misses, are in
[Testing & Evals](docs/testing.md).

## Try it without installing anything into your repos

Every command here only reads. Nothing is written to any repository, no
assistant is reconfigured, and no hook is installed.

```bash
pipx install agi-memory
agi-memory history-import --limit 20     # index the sessions already on this machine
agi-memory stats                         # what it knows, right now
agi-recall "webhook retry"               # search it
```

`stats` prints a count on any machine, so this cannot come back empty and
leave you thinking it is broken. If the numbers look useful, the next section
wires it into your assistants.

## Install

```bash
pipx install agi-memory            # or: brew tap kdbhalala/agi-memory https://github.com/kdbhalala/agi-memory && brew install agi-memory
agi-integrate install all          # connect every assistant it finds on your machine
agi-integrate status               # see what got connected
```

`install all` configures the assistants on this machine. It does **not** write
git hooks into whatever directory you happen to be standing in — it asks
first, and names the repository it is about to write to:

```
  Install git hooks into /Users/you/some-repo? [y/N]:
```

Hooks are per-repository, so install them where you want them:

```bash
cd your-repo && agi-integrate hooks git
```

## Day-1: import your session history

New vault, years of sessions already on disk — start full, not empty. The
installer offers this and **asks first**:

```
  Session History Import
  claude       3913 sessions   readable
  codex          53 sessions   readable
  opencode       17 sessions   readable
  agy                        skipped: conversations are protobuf blobs with no published schema
  hermes                     skipped: sessions are API request dumps containing auth headers -- never read

Import your session history? [Y/n]:
```

Answer yes and every session is indexed into episodic history, so
`memory_timeline` and `memory_wip` work immediately; the 50 most recent also
become searchable memories. A few seconds, entirely on-device, idempotent.
Nothing is read until you agree, and a non-interactive run skips it and tells
you the command instead.

```bash
agi-memory history-import --limit 20            # recent sessions -> L1 digests
agi-memory history-import --index                # every session -> episodic history
agi-memory history-import --harness codex --project my-app
agi-bootstrap --repo . --with-history             # README + git commits + history, one pass
```

Read today: **Claude Code, Codex, OpenCode.** Every other detected tool is
listed at install with the reason it is skipped, so the gap is visible rather
than implied. `hermes` is refused on purpose — its session files are outbound
API request bodies including auth headers.

Each session becomes one L1 observation (`origin="history-import"`, title
`[claude:1a2b3c4d] ...`, project taken from the session's working directory).
Idempotent: re-runs skip sessions already imported. A digest is the session's
own words — goal, the prompts that drove it, files touched — not a distillation,
because nothing here calls an LLM.

Other install options, including a one-line script and running from source, are
in [Installation](docs/installation.md).

## Documentation

| Guide | What's in it |
|---|---|
| [Installation](docs/installation.md) | Install options, upgrading, lifecycle hooks |
| [CLI Usage](docs/cli.md) | Every `agi-memory` and `agi-integrate` command |
| [Supported Assistants](docs/assistants.md) | Where each assistant's config lives, and the 18 MCP tools |
| [How memory is organised](docs/pillars.md) | Notes, knowledge graph, session history, code index |
| [Architecture](docs/architecture.md) | How the pieces fit together |
| [Vault & Git Sync](docs/sync.md) | The memory files, syncing between machines, compaction |
| [Python API](docs/python-api.md) | Using it directly from Python |
| [Testing & Evals](docs/testing.md) | How it's tested, and where it falls short |
| [Benchmarks](docs/benchmarks.md) | Speed and memory measurements |
| [Hybrid Semantic Recall](docs/semantic.md) | Optional Potion/model2vec vectors fused with BM25 via RRF (`memory_recall` mode) |
| [Integrations](INTEGRATIONS.md) | Manual setup snippets for each assistant |

## License

MIT
