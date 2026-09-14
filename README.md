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

```bash
# With optional hybrid semantic recall (Potion vectors, CPU-only, offline):
pipx install "agi-memory[semantic]"
# Details: [Hybrid Semantic Recall](docs/semantic.md).
```

### Manual setup: OpenCode, Cline, Command Code

`agi-integrate install all` wires every detected assistant automatically
(including OpenCode and Cline). To configure one tool by hand, point it at the
`agi-memory` server (stdio, no arguments — make sure it is on your `PATH`)
and add the memory-discipline rules block from [INTEGRATIONS.md](INTEGRATIONS.md).

**OpenCode** — `~/.config/opencode/opencode.jsonc` (user) or `./opencode.jsonc` (project):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "agent-memory": {
      "type": "local",
      "command": ["agi-memory"],
      "enabled": true
    }
  }
}
```

Rules: append the discipline block to `~/.config/opencode/rules.md` (user)
or `AGENTS.md` (project).

**Cline (VS Code)** — use the MCP panel, or edit the settings file directly:

- Windows: `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`
- macOS: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
- Linux: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "agi-memory",
      "args": [],
      "disabled": false
    }
  }
}
```

Rules: project file `.clinerules/agent-memory.md` with the discipline block.

**Command Code** — one command (user scope, all projects):

```bash
commandcode mcp add --transport stdio agent-memory --scope user -- agi-memory
# alternative JSON form:
# commandcode mcp add-json agent-memory '{"command":"agi-memory","args":[]}' --scope user
```

Project scope instead: `--scope project` (writes a committable `.mcp.json`).
Shortcut: if OpenCode is already wired, run `/import opencode` inside a
Command Code session. Rules: same discipline block in the project's `AGENTS.md`.

Verify any of them with:

```bash
agi-integrate status   # who is detected / configured
agi-integrate test     # MCP handshake + registered tools
```

---

## Documentation

| Guide | What's in it |
|---|---|
| [Benchmarks](docs/benchmarks.md) | Speed and memory measurements |
| [Hybrid Semantic Recall](docs/semantic.md) | Optional Potion/model2vec vectors fused with BM25 via RRF (`memory_recall` mode) |
| [Integrations](INTEGRATIONS.md) | Manual setup snippets for each assistant |

## License

MIT
