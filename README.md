# agi-memory

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

## What it won't do

Search is by keyword, not meaning. If you saved "authentication" and later ask
about "login", it can miss. It helps to use the words you'd search for when
saving something. The measured hit rates, including the misses, are in
[Testing & Evals](docs/testing.md).

## Install

```bash
pipx install agi-memory            # or: brew tap kdbhalala/agi-memory https://github.com/kdbhalala/agi-memory && brew install agi-memory
agi-integrate install all          # connect every assistant it finds on your machine
agi-integrate status               # see what got connected
```

Other install options, including a one-line script and running from source, are
in [Installation](docs/installation.md).

## Documentation

| Guide | What's in it |
|---|---|
| [Benchmarks](docs/benchmarks.md) | Speed and memory measurements |
| [Hybrid Semantic Recall](docs/semantic.md) | Optional Potion/model2vec vectors fused with BM25 via RRF (`memory_recall` mode) |
| [Integrations](INTEGRATIONS.md) | Manual setup snippets for each assistant |

## License

MIT
