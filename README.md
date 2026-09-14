# agi-memory

[![CI](https://github.com/kdbhalala/agi-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/kdbhalala/agi-memory/actions)
[![PyPI](https://img.shields.io/pypi/v/agi-memory.svg)](https://pypi.org/project/agi-memory/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib)-brightgreen.svg)](pyproject.toml)
[![Latency](https://img.shields.io/badge/all%204%20layers-%3C1ms-blue.svg)](docs/benchmarks.md)
[![Evals](https://img.shields.io/badge/L1--L4%20evals-100%25-brightgreen.svg)](docs/testing.md)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**Your AI coding assistant forgets everything between sessions. This remembers.**

Decisions you already made, bugs you already fixed, what happened last session,
how the codebase fits together — kept in a file on your machine and handed back
to the assistant next time, so you stop re-explaining your own project.

Works across **Claude Code**, **Cursor**, **Windsurf**, **OpenAI Codex**, **OpenCode**,
**Antigravity CLI**, **Aider**, **Goose**, **Cline**, **Roo Code**, **Crush**, **Pi**
and **Hermes Agent** — one memory, whichever tool you open.

No dependencies, no vector database, no background daemon. ~32MB of RAM,
sub-millisecond lookups, works offline. Comparable tools install ~500MB of
machine-learning libraries and take 200–500ms per lookup.

---

## Why agi-memory? The 4 Cognitive Memory Pillars

Most AI memory architectures solve only a fragment of developer memory while incurring heavy dependencies or requiring background Node.js daemons. `agi-memory` unifies all four cognitive memory pillars in pure Python stdlib + SQLite (<35MB RAM, <1ms speed, zero external pip dependencies):

| Pillar | Core Question | Replaces | Implementation in `agi-memory` | Latency / Overhead |
|---|---|---|---|---|
| **1. Epistemic** | *"What have we learned?"* | Ad-hoc `.cursorrules`, forgotten bugfixes | `SessionLayer` (SQLite FTS5 + BM25, Core Blocks) | **0.23 ms** (zero tokens) |
| **2. Semantic** | *"What does our information mean & how is it connected?"* | Heavy GraphRAG, Cognee, ChromaDB | `GraphLayer` (Native SQLite Recursive CTEs) | **0.28 ms** (zero tokens) |
| **3. Episodic** | *"What happened during previous agent sessions?"* | `claude-mem` (heavy Node/Bun daemons) | `EpisodicLayer` (SQLite Session History & Lifecycle) | **0.23 ms** (zero daemons) |
| **4. Structural** | *"How is this codebase structurally connected?"* | `Graphify`, Tree-sitter binaries, LSP daemons | `CodeLayer` (stdlib AST + Streaming Regex Graph) | **0.45 ms** (zero daemons) |

Every pillar is scored by its own eval suite — see [Benchmarks](docs/benchmarks.md)
for measured comparisons against Mem0, Zep, Cognee, LangChain and claude-mem,
including a real 13,988-observation production dataset.

---

## Install

```bash
# One-line installer (recommended)
curl -fsSL https://raw.githubusercontent.com/kdbhalala/agi-memory/main/install.sh | bash

# Or: Homebrew / PyPI
brew tap kdbhalala/agi-memory https://github.com/kdbhalala/agi-memory && brew install agi-memory
pipx install agi-memory

# With optional hybrid semantic recall (Potion vectors, CPU-only, offline):
pipx install "agi-memory[semantic]"
# Details: [Hybrid Semantic Recall](docs/semantic.md).
```

Then wire up your assistants and initialize a project:

```bash
agi-integrate install all     # configure every detected assistant + lifecycle hooks
agi-integrate status          # confirm what was detected and configured
cd your-project && agi-integrate init .
```

`init` wires the project and installs an `/agi-init` slash command in each
assistant's own format. Run `/agi-init` inside your assistant and it reads the
codebase and writes the project's `rules/` and `context/` files.

Full options, including uvx and from-source: [Installation](docs/installation.md).

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
| [Installation](docs/installation.md) | Installer script, Homebrew, PyPI/uvx, from-source, hooks setup |
| [The Four Pillars](docs/pillars.md) | Deep dive into L1 Epistemic, L2 Semantic, L3 Episodic, L4 Code Graph |
| [Architecture](docs/architecture.md) | Layer boundaries, storage model, multi-assistant production layout |
| [Supported Assistants](docs/assistants.md) | Per-tool config paths and rules files for all 13 assistants |
| [CLI Usage](docs/cli.md) | Every `agi-memory` and `agi-integrate` subcommand |
| [Python API](docs/python-api.md) | Using the layers directly from Python |
| [Vault & Git Sync](docs/sync.md) | Append-only JSONL vault, cross-device sync, compaction |
| [Benchmarks](docs/benchmarks.md) | Latency, memory and cost comparisons; real-dataset results |
| [Hybrid Semantic Recall](docs/semantic.md) | Optional Potion/model2vec vectors fused with BM25 via RRF (`memory_recall` mode) |
| [Testing & Evals](docs/testing.md) | The L1-L4 eval suites, chaos and stress tests |
| [Integrations](INTEGRATIONS.md) | Manual per-tool configuration snippets |

---

## License

MIT
