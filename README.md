# agi-memory

> **Retired.** This project is archived and no longer maintained. Its successor
> for shared coding-agent memory is
> [deja-vu](https://github.com/vshulcz/deja-vu), which builds the memory layer
> from session history already on disk instead of record-forward notes.
> Install it with `curl -fsSL https://raw.githubusercontent.com/vshulcz/deja-vu/main/install.sh | sh`
> followed by `deja install --auto`.

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
| [Installation](docs/installation.md) | Install options, upgrading, lifecycle hooks |
| [CLI Usage](docs/cli.md) | Every `agi-memory` and `agi-integrate` command |
| [Supported Assistants](docs/assistants.md) | Where each assistant's config lives, and the 16 MCP tools |
| [How memory is organised](docs/pillars.md) | Notes, knowledge graph, session history, code index |
| [Architecture](docs/architecture.md) | How the pieces fit together |
| [Vault & Git Sync](docs/sync.md) | The memory files, syncing between machines, compaction |
| [Python API](docs/python-api.md) | Using it directly from Python |
| [Testing & Evals](docs/testing.md) | How it's tested, and where it falls short |
| [Benchmarks](docs/benchmarks.md) | Speed and memory measurements |
| [Integrations](INTEGRATIONS.md) | Manual setup snippets for each assistant |

## License

MIT
