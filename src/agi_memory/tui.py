"""Zero-dependency Terminal Inspector & Health Dashboard for agi-memory.

Features:
- Pure stdlib & ANSI escape codes (no curses/rich/textual dependencies).
- Real-time 4-pillar memory statistics (L1 observations, L2 graph, L3 episodic, L4 code graph).
- Audit inspection of low-impact memories (test fixtures, noise, unconfirmed, superseded).
- Interactive single-key prune [p] and compact [c].
- Graceful non-interactive fallback (--headless, --once, or non-tty pipes).

Run:
    agi-memory tui
    agi-tui
"""
from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from agi_memory import __version__
    from agi_memory.audit import MemoryAudit
    from agi_memory.config import get_default_db, get_vault_dir
    from agi_memory.layers.base import open_db
    from agi_memory.vault import deduplicate_and_compact
except ImportError:
    from audit import MemoryAudit
    from config import get_default_db, get_vault_dir
    from layers.base import open_db
    from vault import deduplicate_and_compact
    __version__ = "0.12.0"

# ANSI styles
ESC = "\033["
RESET = f"{ESC}0m"
BOLD = f"{ESC}1m"
DIM = f"{ESC}2m"
CYAN = f"{ESC}36m"
GREEN = f"{ESC}32m"
YELLOW = f"{ESC}33m"
RED = f"{ESC}31m"
MAGENTA = f"{ESC}35m"
BLUE = f"{ESC}34m"
BG_DARK = f"{ESC}48;5;236m"
CLEAR_SCREEN = f"{ESC}2J{ESC}H"
HIDE_CURSOR = f"{ESC}?25l"
SHOW_CURSOR = f"{ESC}?25h"


def _read_single_key(timeout: float = 0.1) -> str:
    """Read a single keypress without blocking indefinitely."""
    if not sys.stdin.isatty():
        return ""

    if os.name == "nt":
        try:
            import msvcrt
            start_t = time.time()
            while time.time() - start_t < timeout:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    try:
                        return ch.decode("utf-8")
                    except UnicodeDecodeError:
                        return ""
                time.sleep(0.01)
            return ""
        except ImportError:
            return ""

    # Unix / macOS
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        rlist, _, _ = select.select([sys.stdin], [], [], timeout)
        if rlist:
            ch = sys.stdin.read(1)
            return ch
    except Exception:
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ""


def gather_stats(db_path: Path, vault_dir: Path) -> Dict[str, Any]:
    """Collect 4-pillar metrics from SQLite database and vault."""
    stats: Dict[str, Any] = {
        "db_path": str(db_path),
        "db_size_mb": 0.0,
        "vault_lines": 0,
        "l1_observations": 0,
        "pinned_blocks": 0,
        "l2_entities": 0,
        "l2_active_edges": 0,
        "l3_sessions": 0,
        "l4_symbols": 0,
        "l4_files": 0,
        "projects": {},
        "recall_shown": 0,
        "recall_cited": 0,
    }
    if db_path.exists():
        try:
            stats["db_size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2)
        except OSError:
            pass

    obs_vault = vault_dir / "observations.jsonl"
    if obs_vault.exists():
        try:
            with open(obs_vault, "r", encoding="utf-8", errors="ignore") as f:
                stats["vault_lines"] = sum(1 for line in f if line.strip())
        except OSError:
            pass

    if not db_path.exists():
        return stats

    con = open_db(db_path, readonly=True)
    try:
        def _count(query: str) -> int:
            try:
                cur = con.execute(query)
                row = cur.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
            except sqlite3.Error:
                return 0

        stats["l1_observations"] = _count("SELECT COUNT(*) FROM observations")
        stats["pinned_blocks"] = _count("SELECT COUNT(*) FROM core_memory_blocks WHERE status = 'pinned'")
        stats["l2_entities"] = _count("SELECT COUNT(*) FROM graph_nodes")
        stats["l2_active_edges"] = _count("SELECT COUNT(*) FROM graph_edges WHERE is_active = 1")
        stats["l3_sessions"] = _count("SELECT COUNT(DISTINCT session_id) FROM episodic_sessions")
        stats["l4_symbols"] = _count("SELECT COUNT(*) FROM code_symbols")
        stats["l4_files"] = _count("SELECT COUNT(*) FROM code_files")

        cur = con.execute("SELECT project, COUNT(*) FROM observations GROUP BY project ORDER BY 2 DESC LIMIT 8")
        stats["projects"] = {r[0] or "default": r[1] for r in cur.fetchall()}

        stats["recall_shown"] = _count("SELECT COUNT(*) FROM memory_usage")
        stats["recall_cited"] = _count("SELECT COUNT(*) FROM memory_usage WHERE cited_count > 0")
    except Exception:
        pass
    finally:
        con.close()

    return stats


class TerminalInspector:
    def __init__(self, db_path: Optional[Path] = None, vault_dir: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else get_default_db()
        self.vault_dir = Path(vault_dir) if vault_dir else get_vault_dir()
        self.active_tab = 1  # 1: Health & Stats, 2: Audit Candidates
        self.flash_message: Optional[str] = None
        self.flash_until: float = 0.0
        self.cached_audit: Optional[Dict[str, Any]] = None

    def set_flash(self, message: str, duration: float = 3.0) -> None:
        self.flash_message = message
        self.flash_until = time.time() + duration

    def render(self) -> str:
        cols, _ = shutil.get_terminal_size((80, 24))
        width = max(cols - 2, 60)
        border = "═" * width
        thin_border = "─" * width

        lines = []
        # Header
        lines.append(f"{CYAN}{BOLD}╔{border}╗{RESET}")
        title = f" agi-memory terminal inspector v{__version__} "
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        head_sp = width - len(title) - len(now_str) - 2
        lines.append(f"{CYAN}{BOLD}║{RESET} {BOLD}{title}{RESET}{' ' * max(head_sp, 0)}{DIM}{now_str}{RESET} {CYAN}{BOLD}║{RESET}")
        lines.append(f"{CYAN}{BOLD}╠{border}╣{RESET}")

        # Tabs bar
        tab1_style = f"{BOLD}{GREEN}► [1] Health & Metrics{RESET}" if self.active_tab == 1 else f"{DIM}[1] Health & Metrics{RESET}"
        tab2_style = f"{BOLD}{YELLOW}► [2] Audit & Drift Hygiene{RESET}" if self.active_tab == 2 else f"{DIM}[2] Audit & Drift Hygiene{RESET}"
        lines.append(f"{CYAN}{BOLD}║{RESET}  {tab1_style}    {tab2_style}  {CYAN}{BOLD}║{RESET}")
        lines.append(f"{CYAN}{BOLD}╠{border}╣{RESET}")

        # Content by tab
        if self.active_tab == 1:
            stats = gather_stats(self.db_path, self.vault_dir)
            lines.append(f"{CYAN}{BOLD}║{RESET}  {BOLD}Storage & Connectivity{RESET}")
            lines.append(f"{CYAN}{BOLD}║{RESET}    Database:  {stats['db_path']} ({stats['db_size_mb']} MB)")
            lines.append(f"{CYAN}{BOLD}║{RESET}    Vault:     {self.vault_dir} ({stats['vault_lines']} records)")
            lines.append(f"{CYAN}{BOLD}║{RESET}")
            lines.append(f"{CYAN}{BOLD}║{RESET}  {BOLD}Four-Pillar Architecture{RESET}")
            lines.append(f"{CYAN}{BOLD}║{RESET}    {BLUE}● L1 Epistemic Working Memory:{RESET}   {stats['l1_observations']} records ({stats['pinned_blocks']} pinned core blocks)")
            lines.append(f"{CYAN}{BOLD}║{RESET}    {MAGENTA}● L2 Durable Knowledge Graph:{RESET}   {stats['l2_entities']} entities, {stats['l2_active_edges']} active relations")
            lines.append(f"{CYAN}{BOLD}║{RESET}    {CYAN}● L3 Episodic Session Events:{RESET}   {stats['l3_sessions']} tracked agent sessions")
            lines.append(f"{CYAN}{BOLD}║{RESET}    {GREEN}● L4 Code Graph (AST Hashing):{RESET}  {stats['l4_symbols']} symbols across {stats['l4_files']} files")
            lines.append(f"{CYAN}{BOLD}║{RESET}")
            lines.append(f"{CYAN}{BOLD}║{RESET}  {BOLD}Usage & Provenance{RESET}")
            lines.append(f"{CYAN}{BOLD}║{RESET}    Recalled memories surfaced: {stats['recall_shown']} | Citations in decisions: {stats['recall_cited']}")
            if stats["projects"]:
                proj_line = ", ".join(f"{k} ({v})" for k, v in list(stats["projects"].items())[:5])
                lines.append(f"{CYAN}{BOLD}║{RESET}    Top Projects: {proj_line}")
        else:
            if self.cached_audit is None:
                self.cached_audit = MemoryAudit(self.db_path, self.vault_dir).scan()
            audit = self.cached_audit
            lines.append(f"{CYAN}{BOLD}║{RESET}  {BOLD}Memory Store Hygiene Scan ({audit['total_observations']} observations){RESET}")
            lines.append(f"{CYAN}{BOLD}║{RESET}  {thin_border}")

            tf = len(audit["test_fixtures"])
            tf_color = GREEN if tf == 0 else RED
            lines.append(f"{CYAN}{BOLD}║{RESET}    {tf_color}• Synthetic Test Fixtures:{RESET}       {tf}")

            nr = len(audit["noise_records"])
            nr_color = GREEN if nr == 0 else YELLOW
            lines.append(f"{CYAN}{BOLD}║{RESET}    {nr_color}• Zero-Signal Noise Records:{RESET}     {nr}")

            sr = len(audit["superseded_records"])
            lines.append(f"{CYAN}{BOLD}║{RESET}    {BLUE}• Superseded Records:{RESET}            {sr}")

            uc = len(audit["unconfirmed_zero_use"])
            lines.append(f"{CYAN}{BOLD}║{RESET}    {MAGENTA}• Unconfirmed 0-Relevance Records:{RESET} {uc}")
            lines.append(f"{CYAN}{BOLD}║{RESET}")
            if tf > 0 or nr > 0:
                lines.append(f"{CYAN}{BOLD}║{RESET}    {YELLOW}Action Available: Press [p] to prune {tf + nr} fixtures and noise records.{RESET}")
            else:
                lines.append(f"{CYAN}{BOLD}║{RESET}    {GREEN}✓ Clean store! No test fixtures or noise detected.{RESET}")

        # Flash message or status
        lines.append(f"{CYAN}{BOLD}║{RESET}")
        if self.flash_message and time.time() < self.flash_until:
            lines.append(f"{CYAN}{BOLD}║{RESET}  {GREEN}{BOLD}{self.flash_message}{RESET}")
        else:
            lines.append(f"{CYAN}{BOLD}║{RESET}  {DIM}Press keys below to navigate or run hygiene actions.{RESET}")

        # Footer
        lines.append(f"{CYAN}{BOLD}╠{border}╣{RESET}")
        keys_help = f" [1] Stats  [2] Audit  [p] Prune Candidates  [c] Compact Vault  [r] Refresh  [q] Quit "
        sp_footer = width - len(keys_help)
        lines.append(f"{CYAN}{BOLD}║{RESET}{BOLD}{keys_help}{RESET}{' ' * max(sp_footer, 0)}{CYAN}{BOLD}║{RESET}")
        lines.append(f"{CYAN}{BOLD}╚{border}╝{RESET}")
        return "\n".join(lines)

    def run_interactive(self) -> None:
        """Run interactive ANSI dashboard loop."""
        sys.stdout.write(HIDE_CURSOR)
        sys.stdout.flush()
        try:
            while True:
                output = f"{CLEAR_SCREEN}{self.render()}"
                sys.stdout.write(output)
                sys.stdout.flush()

                key = _read_single_key(timeout=0.25)
                if not key:
                    continue

                k = key.lower()
                if k == "q" or key == "\x03":  # q or Ctrl+C
                    break
                elif k == "1":
                    self.active_tab = 1
                elif k == "2":
                    self.active_tab = 2
                    self.cached_audit = None  # trigger rescan
                elif k == "r":
                    self.cached_audit = None
                    self.set_flash("✓ Refreshed metrics and scan.")
                elif k == "p":
                    auditor = MemoryAudit(self.db_path, self.vault_dir)
                    res = auditor.prune_candidates(("test_fixtures", "noise_records"))
                    self.cached_audit = None
                    self.set_flash(f"✓ Pruned {res['pruned_direct']} records; compacted {res['observations_compacted']}.")
                elif k == "c":
                    res = deduplicate_and_compact(vault_dir=self.vault_dir, session_db=self.db_path)
                    self.cached_audit = None
                    self.set_flash(f"✓ Vault compacted ({res.get('observations_pruned', 0)} pruned).")
        finally:
            sys.stdout.write(SHOW_CURSOR + "\n")
            sys.stdout.flush()

    def run_once(self) -> None:
        """Render once to stdout without interactive loop."""
        print(self.render())


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="agi-memory tui", description="Terminal Inspector and Health Dashboard")
    parser.add_argument("--once", "--headless", action="store_true", help="Print dashboard once and exit")
    parser.add_argument("--tab", type=int, choices=[1, 2], default=1, help="Starting tab (1: health, 2: audit)")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    inspector = TerminalInspector()
    inspector.active_tab = args.tab

    if args.once or not sys.stdin.isatty():
        inspector.run_once()
    else:
        inspector.run_interactive()


if __name__ == "__main__":
    main()
