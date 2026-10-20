# Changelog

All notable changes to `agi-memory` are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.14.0] - 2026-10-20

### Added
- **God-Mode Terminal Inspector & Cognitive Dashboard (`agi-tui` / `agi-memory tui`)**:
  - **6 Dedicated Cognitive Tabs**:
    - `[1] Health & Metrics`: Complete 4-pillar overview, vault health, storage size, top project distributions, and empirical citation metrics.
    - `[2] Memory Explorer (Split-Pane)`: Split-pane browser with left-side list and right-side inspection pane (narrative, facts, concepts, modified files).
    - `[3] Knowledge Graph`: Top connected entities, active semantic relations, and factual edge assertions.
    - `[4] Code Graph & AST`: Real-time symbol table, AST drift hashes, and caller hierarchy.
    - `[5] Sessions & WIP`: Chronological agent sessions, outcomes (`completed`/`unknown`/`failed`), duration, git branch, and open WIP items.
    - `[6] Store Hygiene & Audit`: Instant scanner for synthetic fixtures, zero-signal noise records, unconfirmed observations, with one-key prune (`[p]`) and compact (`[c]`).
  - **Live In-TUI Search (`/`)**: Instant SQLite FTS5 search directly inside the TUI with real-time filtering as you type.
  - **Project Filter Cycling (`o`)**: Cycle active project view across all indexed projects with one keystroke.
  - **Vim & Lazygit Ergonomics**: Support for `j`/`k`/`g`/`G` scrolling, arrow keys, `Tab`/`Shift-Tab`, and `Enter`.
  - **Modal Help Overlay (`?`)**: Full floating keyboard shortcuts cheatsheet available on demand.
  - **Zero-Dependency Native Architecture**: Built 100% on Python standard library without curses, rich, or textual.

---

## [0.13.2] - 2026-10-20

### Fixed
- **Terminal Inspector Responsiveness & Feedback (`agi-tui`)**:
  - Maintained stable terminal `cbreak` mode across session loop to eliminate `tcsetattr` terminal attribute thrashing and stutter in multiplexers (`mxterm`, `tmux`).
  - Added immediate visual loading states (`⏳`) and instant stdout flushes for prune (`[p]`), compact (`[c]`), and refresh (`[r]`) operations before executing long-running background tasks.
  - Added support for Arrow keys (`←`, `→`) and `Tab` to navigate smoothly between tabs.
  - Added instant visual feedback when pressing unmapped keys so the user sees input acknowledgment and available action shortcuts.
  - Replaced full-screen buffer clears on regular refresh ticks with cursor repositioning (`\033[H`) to prevent screen flicker.

---

## [0.13.1] - 2026-10-20

### Fixed
- **Terminal Inspector Citation Metrics**:
  - Corrected `Citations in decisions` metric in `agi-tui` to query `memory_usage.cited_count` instead of unpopulated `observations.relevance_count`.
  - Accurately reports downstream memory citations shaping agent decisions.

---

## [0.13.0] - 2026-10-20

### Added
- **Aggressive Stress Benchmark Suites & Multi-Language AST Drift**:
  - Expanded LongTerm-SWE Multi-Language Code Drift Benchmark (`tests/eval_drift_benchmark.py`) from 20 to 30 scenarios across Python, TypeScript, Go, Rust, and Dart.
  - Achieves **100% (30/30)** accuracy in **2.56ms mean latency** with **0 tokens** consumed.
  - Added 250-session, 55-query aggressive stress suite to LongMemEval (`tests/eval_longmemeval.py --stress`) across 6 projects.
  - Stress results: **100% (55/55)** accuracy, **Recall@1**: 87.3%, **Recall@3**: 96.4%, **MRR**: 0.927 in **0.80ms mean latency** with **0 tokens** consumed.
- **Windows Background Console Suppression**:
  - Suppressed disruptive console popups via `subprocess.CREATE_NO_WINDOW` on Windows platforms during background and CLI task dispatch.
- **Vault Freshness Auto-Convergence**:
  - Automatic vault freshness checks and background observation synchronization convergence.
- **Release Automation Idempotency**:
  - Idempotent GitHub release creation and asset upload handling in release workflows.

### Fixed
- **Table Name References in Stats & TUI**:
  - Corrected L2 entity and L3 session table references in `agi-memory stats` and the TUI terminal inspector.

---

## [0.12.0] - 2026-10-20

### Added
- **AST Symbol Drift Detection (`CodeLayer.detect_symbol_drift`)**:
  - Zero-token normalized AST hashing (`_compute_ast_hash`) for Python classes, functions, async functions, and module constants.
  - Normalizes out docstrings, comments, and whitespace formatting changes to prevent alert fatigue.
  - Multi-language drift detection across Python, TypeScript, and Go.
- **Evidence-Based Drift Findings (`findings.py`)**:
  - Automatically checks recalled observations against live disk AST.
  - Neutral evidence prompt: `#{id} references '{symbol}' in {file} whose code implementation has drifted ({change}). Check its claim against current code.`
- **Zero-Dependency Terminal Inspector (`agi-memory tui` / `agi-tui`)**:
  - Pure stdlib ANSI dashboard with interactive tabs: `[1] Health & Metrics` and `[2] Audit & Drift Hygiene`.
  - Single-key actions: `[p]` to prune low-impact records, `[c]` to compact vault, `[r]` to refresh.
  - Headless fallback (`--headless` / `--once`) for non-interactive scripts and CI pipelines.
- **Memory Store Audit & Hygiene Engine (`agi-memory audit`)**:
  - Automatically identifies synthetic test fixtures (`test-*`, `p`, `x`), zero-signal noise records, and unconfirmed zero-citation memories.
  - Prunes test artifacts and tombstone vault entries safely via `agi-memory audit --prune`.
- **LongTerm-SWE Multi-Language Code Drift Benchmark (`tests/eval_drift_benchmark.py`)**:
  - 20 realistic multi-session scenarios across Python, TypeScript, and Go.
  - Achieves **100% (20/20)** drift detection accuracy in **2.22ms mean latency** with **0 tokens** consumed.
- **LongMemEval 100-Session, 50-Query Benchmark Suite (`tests/eval_longmemeval.py`)**:
  - 100 chronological developer sessions spanning 6 enterprise projects.
  - Evaluates Temporal Needle Retrieval (depths 1..95), Cascading Supersession, Multi-Hop Synthesis, Distractor Resistance, and Event Chronology.
  - Achieves **100% (50/50)** accuracy, **Recall@1**: 86.0%, **Recall@3**: 100%, **MRR**: 0.923 in **0.68ms mean latency**.
- **New CLI Entrypoints**:
  - `agi-tui` and `agent-tui`
  - `agi-audit` and `agent-audit`

### Fixed
- **Windows SQLite File Handle Lock**: Explicitly closed open SQLite database connection before temporary directory cleanup in test suites, resolving `PermissionError [WinError 32]` on Windows runners.
- **Release Parity Enforcement**: Synchronized `install.sh` and Homebrew formulae (`Formula/agi-memory.rb`, `Formula/agent-memory.rb`) with `pyproject.toml` version declarations.

---

## [0.11.0] - 2026-10-19

### Added
- Antigravity conversation discovery and transcript indexing.
- Batch episodic session history import (`agi-memory history-import --index`).
- Token budgeting and response caps (`max_bytes`, `max_tokens`) across recall tools.

---

## [0.10.0] - 2026-10-15

### Added
- Native Structural Code Graph (L4) parsing Python, TypeScript, JavaScript, Go, Rust, and Dart.
- Recursive blast-radius impact analysis (`code_impact`) and call hierarchy traversal (`code_callers`, `code_dependencies`).

---

## [0.9.0] - 2026-10-01

### Added
- Multi-device Git vault synchronization (`agi-memory sync`) with append-only JSONL compaction.
- Core memory pinned blocks (`memory_pin`, `memory_unpin`, `memory_blocks`).
- Bi-temporal contradiction tagging and knowledge graph promotion (`memory_promote`).
