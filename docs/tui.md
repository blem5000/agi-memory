# Terminal Inspector & Cognitive Dashboard (`agi-tui`)

`agi-tui` (also available as `agent-tui` or `agi-memory tui`) is a turnkey, zero-dependency terminal dashboard and interactive memory explorer for `agi-memory`. It runs 100% on the Python standard library using native ANSI escape codes—no `curses`, `rich`, or `textual` dependencies required.

---

## ⚡ Quick Start

### For Human Developers (Interactive Mode)
Launch the interactive dashboard from any repository or terminal:

```bash
agi-tui
# or
agi-memory tui
```

### For AI Coding Assistants & Scripts (Headless Mode)
AI agents and CI pipelines should never launch an interactive TTY loop. Instead, pass `--once` (or `--headless`) to capture a clean, non-interactive snapshot of memory state:

```bash
# Capture full system health snapshot
agi-tui --once

# Inspect specific tab (e.g. Tab 2: Explorer with initial search)
agi-tui --tab 2 --search "jwt auth" --once

# Inspect Store Hygiene & Prune Candidates
agi-tui --tab 6 --once

# Filter snapshot by project
agi-tui --tab 2 --project "my-app" --once
```

> **Agent Tip**: When piping output or running in subshells, `agi-tui` automatically detects non-TTY environments (`sys.stdin.isatty() == False`) and defaults to `--once` mode safely without blocking.

---

## 🖥️ Screen Layout & Adaptive Geometry

The TUI automatically detects terminal dimensions via `shutil.get_terminal_size()`:
- **Wide Mode (≥ 84 columns)**: Renders an ergonomic **Split-Pane** view (navigable list on the left, full inspector pane on the right).
- **Compact Mode (< 84 columns)**: Renders a clean **Stacked** view to prevent horizontal overflow in mobile shells or narrow splits.
- **Multiplexer Optimized**: Uses cursor repositioning (`\033[H`) on regular refresh ticks rather than full screen clears (`\033[2J`), eliminating flicker inside `mxterm`, `tmux`, and SSH sessions.

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
║  ⚡ agi-memory god-mode inspector v0.14.0                                     2026-10-20 15:35:16 ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════╣
║  [1] Health & Metrics  [2] Memory Explorer  [3] Knowledge Graph  [4] Code AST  [5] Sessions  [6] Audit║
╠══════════════════════════════════════════════════════════════════════════════════════════════════╣
║ Memories (50)                              │Observation #167115: Refresh-token rotation design   ║
║ ─────────────────────────────────────────  │──────────────────────────────────────────────────   ║
║ ❯ #167115 [arch] Refresh-token rotation d  │  Project:    MobileAppAPI                           ║
║   #166994 [patt] Wasm guard pattern alrea  │  Category:   architecture  |  Created: 2026-09-30   ║
║   #166990 [bugf] Pattern found. One new s  │  Concepts:   ["architecture", "security", "jwt"]   ║
║   #166926 [deci] change icon for city and  │  Modified:   ["AuthService.cs", "TokenEndpoint.cs"] ║
║   #166885 [deci] implement deep link hand  │                                                     ║
║                                            │  Narrative & Synthesis:                             ║
║                                            │    MobileAppAPI (.NET 10 API): sessions use short-  ║
║                                            │    lived JWT access tokens with rotating refresh.   ║
║                                            │                                                     ║
║                                            │  Key Technical Facts:                               ║
║                                            │    • Rotating refresh tokens stored in Keychain     ║
║                                            │    • Access tokens expire in 15 minutes             ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════╣
║  Project: All Projects | Search: 'refresh'                                                       ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════╣
║ [1-6] Tabs  [j/k/↑/↓] Scroll  [/] Search  [o] Project  [p] Prune  [c] Compact  [?] Help  [q] Quit ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 📑 The 6 Cognitive Tabs

### `[1] Health & Metrics`
- **Storage & Connectivity**: Live SQLite database size, memory vault path, line count, and Git auto-sync connection status.
- **Four-Pillar Overview**: Real-time totals for L1 Working Memory, L2 Knowledge Graph, L3 Episodic Sessions, and L4 Structural Code AST.
- **Empirical Utility**:
  - `Recalled Memories Surfaced`: Total count of observations injected into agent prompts.
  - `Downstream Citations in #id`: Number of times an agent explicitly cited a recalled memory `#id` when making subsequent code decisions.
- **Project Distribution**: Proportional visual distribution bars showing observations per project.

### `[2] Memory Explorer` (Split-Pane Browser)
- **Left Pane (List View)**: Scrollable list of observations with record ID (`#101`), colorized type badges (`[arch]`, `[deci]`, `[bugf]`, `[patt]`, `[perf]`), and descriptive titles.
- **Right Pane (Inspector View)**:
  - Observation metadata: Project, Category, Creation timestamp, Content Hash.
  - Extracted concepts and modified files.
  - Full narrative text.
  - Formatted technical facts bullet list.
  - Supersession alerts if superseded by a newer record.
- **Actions**:
  - Press `/` to start instant live search.
  - Press `o` or `p` to cycle active project filter.
  - Press `d` to soft-delete (mark superseded) the selected memory.

### `[3] Knowledge Graph` (Interactive Visual Topology & Traversal)
- **Left Pane (Entity Directory)**: Top semantic entities and concepts ranked by edge connectivity count (`edge_count`).
- **Right Pane (Directed Ego-Tree Graph Canvas)**:
  - **Inbound Predecessors**: Upstream nodes pointing into the focal node (`Node ──[REL]──► (focal)`).
  - **Hero Focal Node Card**: Box capsule displaying active entity name, entity type, and active edge count.
  - **Outbound Successors**: Downstream dependencies (`(focal) ──[REL]──► Target`).
  - **Factual Context**: Attached technical assertions validating the active relationships.
- **Graph Traversal Actions**:
  - Press `Tab` or `l` / `→` to switch focus into the visual graph canvas.
  - Press `j` / `k` or `↑` / `↓` to select connected neighbor nodes.
  - Press `Enter` on any highlighted neighbor to **hop** to that node, re-centering the graph canvas and loading its neighborhood immediately.
  - Press `u` or `Backspace` to navigate back through the traversal history stack.
  - Press `Esc` or `h` / `←` to return focus to the entity directory.

### `[4] Code Graph & AST`
- Real-time symbol table indexing functions, classes, and methods across the codebase.
- File path, start line, end line, and kind badges.
- **AST Drift Hashes**: Displays normalized AST hashes used to detect when code implementations evolve across developer sessions.

### `[5] Sessions & WIP`
- Chronological timeline of AI coding sessions across harnesses (Claude Code, Codex, OpenCode, Antigravity).
- Duration, Git branch, outcome status (`completed`, `active`, `unknown`, `failed`), and goal/summary.
- Helps developers and agents verify recent work without reading raw JSONL logs.

### `[6] Audit & Store Hygiene`
- Runs a non-destructive audit scan of the memory vault.
- Detects:
  - **Synthetic Test Fixtures**: Contaminated records created by test suites (`test-*`, `sample-*`).
  - **Zero-Signal Noise Records**: Vague prompt fragments without actionable technical content.
  - **Superseded Records**: Obsolete decisions that have been replaced.
  - **Unconfirmed 0-Relevance Records**: Speculative entries never validated by recall.
- **Direct Actions**:
  - Press `p` to prune fixtures and noise records.
  - Press `c` to compact vault JSONL files and rebuild SQLite indexes.

---

## ⌨️ Complete Keyboard Shortcuts Reference

| Key(s) | Context | Action | Description |
|---|---|---|---|
| `1` – `6` | Global | Jump to Tab | Instantly switch to Tab 1 (`Health`), 2 (`Explorer`), 3 (`Graph`), 4 (`Code`), 5 (`Sessions`), or 6 (`Audit`). |
| `Tab` / `Shift-Tab` | Global | Next / Prev Tab | Cycle forward or backward through tabs. |
| `←` / `→` or `h` / `l` | Global | Next / Prev Tab | Vim-style or arrow key tab navigation. |
| `↑` / `↓` or `j` / `k` | Explorer / Graph / Lists | Scroll Up / Down | Move selected row pointer. |
| `g` / `G` | Lists | Top / Bottom | Jump to the first or last record in the list. |
| `/` | Explorer | Live FTS5 Search | Open search input prompt. Filters memories in real-time. |
| `Enter` | Search Mode | Commit Search | Lock in search query and focus the filtered results list. |
| `Esc` | Search / Modal | Cancel / Clear | Exit search mode, clear search filter, or dismiss help modal. |
| `o` or `p` | Explorer | Cycle Project Filter | Cycle view between `All Projects` and specific indexed repositories. |
| `d` | Explorer | Supersede Observation | Mark the currently selected observation as superseded (`superseded_by = -1`). |
| `p` | Audit / Hygiene | Prune Candidates | Prune detected synthetic test fixtures and zero-signal noise records safely. |
| `c` | Global | Compact Vault | Run vault deduplication, prune tombstones, and compact JSONL files. |
| `r` | Global | Refresh | Re-query database and refresh statistics. |
| `?` or `F1` | Global | Help Cheatsheet | Open or close the floating keyboard shortcuts modal overlay. |
| `q` or `Ctrl+C` | Global | Quit | Exit `agi-tui` cleanly, restoring terminal cursor and settings. |

---

## 🔍 In-TUI Live Search (FTS5)

When you press `/` in Tab 2 (`Memory Explorer`), the status bar transforms into a live search prompt:

```
Search (FTS5): auth token_ [Enter: Commit | Esc: Cancel]
```

### Search Features
1. **Sub-millisecond Performance**: Powered directly by SQLite FTS5 index over `title`, `subtitle`, `facts`, `narrative`, and `concepts`.
2. **Prefix Matching**: Typing `auth` automatically matches `authenticate`, `authorization`, and `authorizer`.
3. **Multi-term Conjunction**: Typing `auth token` queries for records containing both terms anywhere in their text or facts.
4. **Instant Cancellation**: Pressing `Esc` clears the search buffer and restores the full memory view immediately.

---

## 🤖 Programmatic CLI Flags

The `agi-memory tui` executable supports the following CLI arguments:

```bash
usage: agi-memory tui [-h] [--once] [--tab {1,2,3,4,5,6}] [--search SEARCH] [--project PROJECT]

options:
  -h, --help            Show this help message and exit
  --once, --headless    Print dashboard snapshot once to stdout and exit
  --tab {1,2,3,4,5,6}   Starting tab (1: health, 2: explorer, 3: graph, 4: code, 5: sessions, 6: audit)
  --search SEARCH       Initial search query to filter memories in Tab 2
  --project PROJECT     Filter view to a specific project name
```

### Examples for Agent Tool Invocation

```python
import subprocess

# Inspect recent decisions about authentication in project "tvlr"
output = subprocess.check_output([
    "agi-tui", "--once",
    "--tab", "2",
    "--project", "tvlr",
    "--search", "authentication"
], text=True)

print(output)
```
