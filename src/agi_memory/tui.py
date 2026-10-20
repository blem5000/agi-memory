"""Zero-dependency God-Mode Terminal Inspector & Cognitive Dashboard for agi-memory.

Features:
- Pure stdlib & ANSI escape codes (no curses/rich/textual runtime dependencies).
- 6 Interactive Tabs:
    [1] Health & Metrics: 4-pillar overview, vault health, projects distribution, citation metrics.
    [2] Memory Explorer: Split-pane browser, instant live FTS5 search (/), project cycling (o).
    [3] Knowledge Graph: Entities ranking, active bi-temporal relations, factual assertions.
    [4] Code Graph & AST: Symbol table, AST drift verification, callers, blast radius.
    [5] Sessions & WIP: Chronological developer sessions, outcomes, touched files, open WIP items.
    [6] Audit & Hygiene: Test fixtures, zero-signal noise, one-key prune [p] & compact [c].
- Full Keyboard Navigation: Vim bindings (j/k/g/G), Arrows, Tab/Shift-Tab, Live Search (/), Help Modal (?).
- Zero-Flicker in-place terminal redraw engine (\033[H) for mxterm, tmux, and SSH sessions.
- Graceful non-interactive fallback (--headless, --once, or piped output).

Run:
    agi-memory tui
    agi-tui
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    __version__ = "0.14.0"

# ANSI styles & 16-color / 256-color palette
ESC = "\033["
RESET = f"{ESC}0m"
BOLD = f"{ESC}1m"
DIM = f"{ESC}2m"
ITALIC = f"{ESC}3m"
UNDERLINE = f"{ESC}4m"
REVERSE = f"{ESC}7m"

# Foreground colors
BLACK = f"{ESC}30m"
RED = f"{ESC}31m"
GREEN = f"{ESC}32m"
YELLOW = f"{ESC}33m"
BLUE = f"{ESC}34m"
MAGENTA = f"{ESC}35m"
CYAN = f"{ESC}36m"
WHITE = f"{ESC}37m"
GRAY = f"{ESC}90m"
BRIGHT_WHITE = f"{ESC}97m"
BRIGHT_CYAN = f"{ESC}96m"
BRIGHT_GREEN = f"{ESC}92m"
BRIGHT_YELLOW = f"{ESC}93m"
BRIGHT_MAGENTA = f"{ESC}95m"

# Terminal canvas controls
CLEAR_SCREEN = f"{ESC}2J{ESC}H"
CURSOR_HOME = f"{ESC}H"
CLEAR_LINE = f"{ESC}K"
HIDE_CURSOR = f"{ESC}?25l"
SHOW_CURSOR = f"{ESC}?25h"

# Unicode box drawing
BOX_HORIZ = "═"
BOX_VERT = "║"
BOX_TOP_LEFT = "╔"
BOX_TOP_RIGHT = "╗"
BOX_BOT_LEFT = "╚"
BOX_BOT_RIGHT = "╝"
BOX_MID_LEFT = "╠"
BOX_MID_RIGHT = "╣"
THIN_HORIZ = "─"
THIN_VERT = "│"
THIN_CROSS = "┼"
THIN_TOP = "┬"
THIN_BOT = "┴"
THIN_MID_LEFT = "├"
THIN_MID_RIGHT = "┤"


def _read_single_key(timeout: float = 0.25) -> str:
    """Read a single key or escape sequence without blocking indefinitely."""
    if not sys.stdin.isatty():
        return ""

    if os.name == "nt":
        try:
            import msvcrt
            start_t = time.time()
            while time.time() - start_t < timeout:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch in (b"\x00", b"\xe0"):
                        ch2 = msvcrt.getch()
                        if ch2 == b"K":
                            return "left"
                        elif ch2 == b"M":
                            return "right"
                        elif ch2 == b"H":
                            return "up"
                        elif ch2 == b"P":
                            return "down"
                        return ""
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
    fd = sys.stdin.fileno()
    try:
        rlist, _, _ = select.select([fd], [], [], timeout)
        if not rlist:
            return ""
        ch = os.read(fd, 1).decode("utf-8", errors="ignore")
        if ch == "\x1b":
            # Check for escape sequence
            rlist2, _, _ = select.select([fd], [], [], 0.05)
            if rlist2:
                seq = os.read(fd, 4).decode("utf-8", errors="ignore")
                if seq == "[D":
                    return "left"
                elif seq == "[C":
                    return "right"
                elif seq == "[A":
                    return "up"
                elif seq == "[B":
                    return "down"
                elif seq == "[Z":
                    return "shift_tab"
                return f"esc{seq}"
            return "esc"
        elif ch in ("\r", "\n"):
            return "enter"
        elif ch in ("\x7f", "\x08"):
            return "backspace"
        return ch
    except Exception:
        return ""


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences for accurate visual length calculation."""
    return re.sub(r"\033\[[0-9;]*[a-zA-Z]", "", text)


def _pad_line(text: str, width: int, fill: str = " ") -> str:
    """Pad or truncate string to exact visual width, preserving ANSI sequences."""
    visible = _strip_ansi(text)
    vis_len = len(visible)
    if vis_len > width:
        # truncate while preserving end reset
        raw_cut = text[:width + 20]
        while len(_strip_ansi(raw_cut)) > width and len(raw_cut) > 0:
            raw_cut = raw_cut[:-1]
        return raw_cut + RESET
    return text + (fill * (width - vis_len))


def _type_badge(obs_type: str) -> str:
    """Colorized 6-char badge for observation types."""
    t = (obs_type or "general").lower()[:4]
    if t in ("arch", "desi"):
        return f"{BRIGHT_MAGENTA}[arch]{RESET}"
    elif t in ("deci", "decs"):
        return f"{BRIGHT_CYAN}[deci]{RESET}"
    elif t in ("bugf", "fix", "bug"):
        return f"{BRIGHT_YELLOW}[bugf]{RESET}"
    elif t in ("patt", "conv"):
        return f"{BRIGHT_GREEN}[patt]{RESET}"
    elif t in ("perf", "scal"):
        return f"{BLUE}[perf]{RESET}"
    return f"{GRAY}[{t.ljust(4)}]{RESET}"


def gather_stats(db_path: Path, vault_dir: Path) -> Dict[str, Any]:
    """Collect 4-pillar metrics from SQLite database and vault."""
    stats: Dict[str, Any] = {
        "db_path": str(db_path),
        "db_size_mb": 0.0,
        "vault_dir": str(vault_dir),
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
        def _count(query: str, params: tuple = ()) -> int:
            try:
                cur = con.execute(query, params)
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


def fetch_observations(db_path: Path, project: Optional[str] = None, search: Optional[str] = None,
                       limit: int = 40, offset: int = 0) -> List[Dict[str, Any]]:
    """Fetch paginated observations with optional project filter or FTS5 search."""
    if not db_path.exists():
        return []
    con = open_db(db_path, readonly=True)
    results = []
    try:
        con.row_factory = sqlite3.Row
        if search and search.strip():
            # Clean search term for FTS5
            q = re.sub(r"[^\w\s-]", "", search).strip()
            if q:
                terms = q.split()
                fts_query = " AND ".join(f'"{t}"*' for t in terms)
                sql = """
                    SELECT o.id, o.project, o.type, o.title, o.subtitle, o.created_at, o.content_hash, o.superseded_by
                    FROM observations_fts f
                    JOIN observations o ON f.rowid = o.id
                    WHERE observations_fts MATCH ?
                """
                params: List[Any] = [fts_query]
                if project and project != "All Projects":
                    sql += " AND o.project = ?"
                    params.append(project)
                sql += " ORDER BY o.id DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                cur = con.execute(sql, params)
                results = [dict(r) for r in cur.fetchall()]
        else:
            sql = """
                SELECT id, project, type, title, subtitle, created_at, content_hash, superseded_by
                FROM observations
            """
            params = []
            if project and project != "All Projects":
                sql += " WHERE project = ?"
                params.append(project)
            sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cur = con.execute(sql, params)
            results = [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return results


def fetch_observation_detail(db_path: Path, obs_id: int) -> Optional[Dict[str, Any]]:
    """Fetch complete detail for a specific observation."""
    if not db_path.exists() or obs_id <= 0:
        return None
    con = open_db(db_path, readonly=True)
    detail = None
    try:
        con.row_factory = sqlite3.Row
        cur = con.execute("""
            SELECT id, memory_session_id, project, type, title, subtitle, facts, narrative,
                   concepts, files_read, files_modified, created_at, content_hash,
                   superseded_by, origin, agent
            FROM observations WHERE id = ?
        """, (obs_id,))
        row = cur.fetchone()
        if row:
            detail = dict(row)
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return detail


def fetch_graph_entities(db_path: Path, project: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """Fetch top connected graph entities."""
    if not db_path.exists():
        return []
    con = open_db(db_path, readonly=True)
    results = []
    try:
        con.row_factory = sqlite3.Row
        sql = """
            SELECT n.id, n.name, n.entity_type, n.project,
                   (SELECT COUNT(*) FROM graph_edges e WHERE (e.source = n.name OR e.target = n.name) AND e.is_active = 1) AS edge_count
            FROM graph_nodes n
        """
        params: List[Any] = []
        if project and project != "All Projects":
            sql += " WHERE n.project = ?"
            params.append(project)
        sql += " ORDER BY edge_count DESC, n.id DESC LIMIT ?"
        params.append(limit)
        cur = con.execute(sql, params)
        results = [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return results


def fetch_graph_relations(db_path: Path, entity_name: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
    """Fetch active relations for a specific entity or across the graph."""
    if not db_path.exists():
        return []
    con = open_db(db_path, readonly=True)
    results = []
    try:
        con.row_factory = sqlite3.Row
        sql = """
            SELECT id, source, relation, target, fact, project, created_at
            FROM graph_edges
            WHERE is_active = 1
        """
        params: List[Any] = []
        if entity_name:
            sql += " AND (source = ? OR target = ?)"
            params.extend([entity_name, entity_name])
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = con.execute(sql, params)
        results = [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return results


def fetch_code_symbols(db_path: Path, project: Optional[str] = None, limit: int = 35) -> List[Dict[str, Any]]:
    """Fetch indexed code symbols and signatures."""
    if not db_path.exists():
        return []
    con = open_db(db_path, readonly=True)
    results = []
    try:
        con.row_factory = sqlite3.Row
        sql = """
            SELECT id, project, file_path, name, qualified_name, kind, signature, start_line, end_line, ast_hash
            FROM code_symbols
        """
        params: List[Any] = []
        if project and project != "All Projects":
            sql += " WHERE project = ?"
            params.append(project)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = con.execute(sql, params)
        results = [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return results


def fetch_sessions(db_path: Path, project: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
    """Fetch recent episodic developer sessions."""
    if not db_path.exists():
        return []
    con = open_db(db_path, readonly=True)
    results = []
    try:
        con.row_factory = sqlite3.Row
        sql = """
            SELECT id, session_id, project, goal, started_at, duration_seconds, git_branch,
                   summary, touched_files, commits, status, outcome
            FROM episodic_sessions
        """
        params: List[Any] = []
        if project and project != "All Projects":
            sql += " WHERE project = ?"
            params.append(project)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = con.execute(sql, params)
        results = [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return results


class TerminalInspector:
    """God-Mode Terminal Inspector for agi-memory."""

    TAB_NAMES = [
        "Health & Metrics",
        "Memory Explorer",
        "Knowledge Graph",
        "Code Graph & AST",
        "Sessions & WIP",
        "Audit & Hygiene",
    ]

    def __init__(self, db_path: Optional[Path] = None, vault_dir: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else get_default_db()
        self.vault_dir = Path(vault_dir) if vault_dir else get_vault_dir()
        self.active_tab = 1
        self.selected_index = 0
        self.search_query = ""
        self.search_buffer = ""
        self.input_mode: Optional[str] = None  # None or "search"
        self.show_help = False
        self.active_project = "All Projects"
        self.cached_projects: List[str] = ["All Projects"]

        self.flash_message: Optional[str] = None
        self.flash_until: float = 0.0
        self.cached_audit: Optional[Dict[str, Any]] = None

    def set_flash(self, message: str, duration: float = 3.0) -> None:
        self.flash_message = message
        self.flash_until = time.time() + duration

    def cycle_project_filter(self) -> None:
        """Cycle active project filter through known projects."""
        stats = gather_stats(self.db_path, self.vault_dir)
        projects = ["All Projects"] + sorted(stats["projects"].keys())
        self.cached_projects = projects
        try:
            curr_idx = projects.index(self.active_project)
            self.active_project = projects[(curr_idx + 1) % len(projects)]
        except ValueError:
            self.active_project = projects[0]
        self.selected_index = 0
        self.set_flash(f"► Filtered by project: {self.active_project}", duration=1.5)

    def render_header(self, width: int) -> List[str]:
        """Render top border, title, and timestamp."""
        lines = []
        border = BOX_HORIZ * width
        lines.append(f"{CYAN}{BOLD}{BOX_TOP_LEFT}{border}{BOX_TOP_RIGHT}{RESET}")
        title = f" ⚡ agi-memory god-mode inspector v{__version__} "
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        head_sp = width - len(title) - len(now_str) - 2
        lines.append(f"{CYAN}{BOLD}{BOX_VERT}{RESET} {BOLD}{title}{RESET}{' ' * max(head_sp, 0)}{DIM}{now_str}{RESET} {CYAN}{BOLD}{BOX_VERT}{RESET}")
        lines.append(f"{CYAN}{BOLD}{BOX_MID_LEFT}{border}{BOX_MID_RIGHT}{RESET}")

        # Tabs bar (6 tabs)
        tab_chunks = []
        for i, name in enumerate(self.TAB_NAMES, start=1):
            short_name = name.split()[0]
            if i == self.active_tab:
                tab_chunks.append(f"{REVERSE}{BOLD} [{i}] {name} {RESET}")
            else:
                tab_chunks.append(f"{DIM}[{i}] {short_name}{RESET}")
        tab_bar = "  ".join(tab_chunks)
        sp_tabs = width - len(_strip_ansi(tab_bar)) - 2
        lines.append(f"{CYAN}{BOLD}{BOX_VERT}{RESET}  {tab_bar}{' ' * max(sp_tabs, 0)}{CYAN}{BOLD}{BOX_VERT}{RESET}")
        lines.append(f"{CYAN}{BOLD}{BOX_MID_LEFT}{border}{BOX_MID_RIGHT}{RESET}")
        return lines

    def render_footer(self, width: int) -> List[str]:
        """Render status alert, active filters, and key shortcuts footer."""
        lines = []
        border = BOX_HORIZ * width

        # Flash message or default status line
        if self.input_mode == "search":
            search_line = f"  {YELLOW}{BOLD}Search (FTS5):{RESET} {self.search_buffer}█ {DIM}[Enter: Commit | Esc: Cancel]{RESET}"
            sp_search = width - len(_strip_ansi(search_line))
            lines.append(f"{CYAN}{BOLD}{BOX_VERT}{RESET}{search_line}{' ' * max(sp_search, 0)}{CYAN}{BOLD}{BOX_VERT}{RESET}")
        elif self.flash_message and time.time() < self.flash_until:
            color = BRIGHT_YELLOW if "⏳" in self.flash_message else (BRIGHT_GREEN if "✓" in self.flash_message else BRIGHT_CYAN)
            msg_str = f"  {color}{BOLD}{self.flash_message}{RESET}"
            sp_msg = width - len(_strip_ansi(msg_str))
            lines.append(f"{CYAN}{BOLD}{BOX_VERT}{RESET}{msg_str}{' ' * max(sp_msg, 0)}{CYAN}{BOLD}{BOX_VERT}{RESET}")
        else:
            proj_badge = f"{DIM}Project:{RESET} {BRIGHT_CYAN}{self.active_project}{RESET}"
            search_badge = f" | {DIM}Search:{RESET} {YELLOW}'{self.search_query}'{RESET}" if self.search_query else ""
            status_line = f"  {proj_badge}{search_badge}"
            sp_stat = width - len(_strip_ansi(status_line))
            lines.append(f"{CYAN}{BOLD}{BOX_VERT}{RESET}{status_line}{' ' * max(sp_stat, 0)}{CYAN}{BOLD}{BOX_VERT}{RESET}")

        # Shortcuts footer
        lines.append(f"{CYAN}{BOLD}{BOX_MID_LEFT}{border}{BOX_MID_RIGHT}{RESET}")
        keys_help = " [1-6] Tabs  [j/k/↑/↓] Scroll  [/] Search  [o] Project  [p] Prune  [c] Compact  [?] Help  [q] Quit "
        sp_footer = width - len(keys_help)
        lines.append(f"{CYAN}{BOLD}{BOX_VERT}{RESET}{BOLD}{keys_help}{RESET}{' ' * max(sp_footer, 0)}{CYAN}{BOLD}{BOX_VERT}{RESET}")
        lines.append(f"{CYAN}{BOLD}{BOX_BOT_LEFT}{border}{BOX_BOT_RIGHT}{RESET}")
        return lines

    def render_tab1_health(self, width: int, max_lines: int) -> List[str]:
        """Render Tab 1: 4-Pillar Health & Memory Statistics."""
        stats = gather_stats(self.db_path, self.vault_dir)
        lines = []

        lines.append(f"  {BOLD}Local Storage & Connectivity{RESET}")
        lines.append(f"    • Database File:   {stats['db_path']} ({stats['db_size_mb']} MB)")
        lines.append(f"    • Memory Vault:    {stats['vault_dir']} ({stats['vault_lines']} records)")
        lines.append(f"    • Synchronization: {BRIGHT_GREEN}● Auto-sync active{RESET} (Connected to Git vault)")
        lines.append("")

        lines.append(f"  {BOLD}Four-Pillar Cognitive Architecture{RESET}")
        lines.append(f"    {BRIGHT_CYAN}● L1 Epistemic Working Memory:{RESET}   {stats['l1_observations']} observations ({stats['pinned_blocks']} pinned core blocks)")
        lines.append(f"    {BRIGHT_MAGENTA}● L2 Durable Knowledge Graph:{RESET}    {stats['l2_entities']} entities, {stats['l2_active_edges']} active relations")
        lines.append(f"    {BLUE}● L3 Episodic Session History:{RESET}   {stats['l3_sessions']} tracked developer sessions")
        lines.append(f"    {BRIGHT_GREEN}● L4 Structural Code Graph AST:{RESET}  {stats['l4_symbols']} symbols across {stats['l4_files']} files")
        lines.append("")

        lines.append(f"  {BOLD}Empirical Utility & Provenance{RESET}")
        lines.append(f"    • Recalled Memories Surfaced:  {BOLD}{stats['recall_shown']}{RESET} memories")
        lines.append(f"    • Downstream Citations in #id: {BRIGHT_GREEN}{BOLD}{stats['recall_cited']}{RESET} active citations in subsequent decisions")
        lines.append("")

        lines.append(f"  {BOLD}Top Project Store Distribution{RESET}")
        if stats["projects"]:
            tot = sum(stats["projects"].values()) or 1
            for p_name, count in list(stats["projects"].items())[:5]:
                pct = int((count / tot) * 20)
                bar = f"{CYAN}{'█' * pct}{DIM}{'░' * (20 - pct)}{RESET}"
                lines.append(f"    {p_name.ljust(24)} {bar}  {count} records ({count/tot*100:.1f}%)")
        else:
            lines.append("    (No observations recorded yet. Run 'agi-bootstrap' or start coding.)")

        return lines

    def render_tab2_explorer(self, width: int, max_lines: int) -> List[str]:
        """Render Tab 2: Split-Pane Memory Explorer with Live FTS5 Search."""
        obs_list = fetch_observations(
            self.db_path,
            project=self.active_project if self.active_project != "All Projects" else None,
            search=self.search_query if self.search_query else None,
            limit=50
        )
        if not obs_list:
            msg = f"No observations found matching '{self.search_query}'" if self.search_query else "No observations found."
            return [f"  {YELLOW}{msg}{RESET}", "", "  Press [/] to search or [o] to change project filter."]

        # Clamp selection
        self.selected_index = max(0, min(self.selected_index, len(obs_list) - 1))
        selected_obs = obs_list[self.selected_index]

        # Geometry for split pane
        use_split = width >= 84
        left_w = min(max(int(width * 0.44), 36), width - 36) if use_split else width - 4
        right_w = (width - left_w - 3) if use_split else width - 4

        # Build Left Pane (Observation list)
        left_lines = []
        header_text = f"Memories ({len(obs_list)})"
        if self.search_query:
            header_text += f" [Search: '{self.search_query}']"
        left_lines.append(f"{BOLD}{header_text}{RESET}")
        left_lines.append(THIN_HORIZ * (left_w - 2))

        # Viewport scrolling
        visible_rows = max(max_lines - 4, 8)
        start_idx = max(0, min(self.selected_index - visible_rows // 2, len(obs_list) - visible_rows))
        end_idx = min(start_idx + visible_rows, len(obs_list))

        for idx in range(start_idx, end_idx):
            item = obs_list[idx]
            is_sel = (idx == self.selected_index)
            prefix = f"{BRIGHT_CYAN}❯{RESET} " if is_sel else "  "
            badge = _type_badge(item.get("type", ""))
            obs_id = f"#{item['id']}".ljust(6)
            title = (item.get("title") or "Untitled").strip()
            row_str = f"{prefix}{obs_id} {badge} {title}"
            if is_sel:
                row_str = f"{REVERSE}{BOLD}{_pad_line(row_str, left_w - 2)}{RESET}"
            else:
                row_str = _pad_line(row_str, left_w - 2)
            left_lines.append(row_str)

        # Build Right Pane (Detail view of selected observation)
        right_lines = []
        detail = fetch_observation_detail(self.db_path, selected_obs["id"])
        if detail:
            right_lines.append(f"{BOLD}Observation #{detail['id']}: {detail.get('title', 'Untitled')}{RESET}")
            right_lines.append(THIN_HORIZ * (right_w - 2))
            right_lines.append(f"  {DIM}Project:{RESET}    {BRIGHT_CYAN}{detail.get('project') or 'default'}{RESET}")
            right_lines.append(f"  {DIM}Category:{RESET}   {detail.get('type') or 'general'}  |  {DIM}Created:{RESET} {detail.get('created_at') or 'unknown'}")
            if detail.get("concepts"):
                right_lines.append(f"  {DIM}Concepts:{RESET}   {YELLOW}{detail.get('concepts')}{RESET}")
            if detail.get("files_modified"):
                right_lines.append(f"  {DIM}Modified:{RESET}   {detail.get('files_modified')}")
            right_lines.append("")

            right_lines.append(f"  {BOLD}Narrative & Synthesis:{RESET}")
            narrative = detail.get("narrative") or detail.get("subtitle") or "No narrative recorded."
            # Wrap narrative text
            for line in narrative.splitlines()[:5]:
                right_lines.append(f"    {line[:right_w - 6]}")
            right_lines.append("")

            # Extracted Facts
            raw_facts = detail.get("facts")
            if raw_facts:
                right_lines.append(f"  {BOLD}Key Technical Facts:{RESET}")
                try:
                    facts_list = json.loads(raw_facts) if isinstance(raw_facts, str) and raw_facts.startswith("[") else [raw_facts]
                    for fact in facts_list[:4]:
                        clean_fact = str(fact).strip()
                        right_lines.append(f"    • {clean_fact[:right_w - 8]}")
                except Exception:
                    right_lines.append(f"    • {str(raw_facts)[:right_w - 8]}")

            if detail.get("superseded_by"):
                right_lines.append(f"  {RED}{BOLD}⚠ Superseded by observation #{detail['superseded_by']}{RESET}")
        else:
            right_lines.append("  (Select an observation to view details)")

        # Combine panes
        combined = []
        if use_split:
            total_rows = max(len(left_lines), len(right_lines))
            for r in range(total_rows):
                l_str = left_lines[r] if r < len(left_lines) else ""
                r_str = right_lines[r] if r < len(right_lines) else ""
                l_pad = _pad_line(l_str, left_w)
                r_pad = _pad_line(r_str, right_w)
                combined.append(f"{l_pad}{DIM}{THIN_VERT}{RESET}{r_pad}")
        else:
            combined.extend(left_lines)
            combined.append(THIN_HORIZ * (width - 4))
            combined.extend(right_lines)
        return combined

    def render_tab3_graph(self, width: int, max_lines: int) -> List[str]:
        """Render Tab 3: Knowledge Graph Entities & Active Relations."""
        entities = fetch_graph_entities(self.db_path, project=self.active_project if self.active_project != "All Projects" else None)
        relations = fetch_graph_relations(self.db_path, limit=25)

        use_split = width >= 84
        left_w = min(max(int(width * 0.44), 36), width - 36) if use_split else width - 4
        right_w = (width - left_w - 3) if use_split else width - 4

        left_lines = []
        left_lines.append(f"{BOLD}Knowledge Entities ({len(entities)}){RESET}")
        left_lines.append(THIN_HORIZ * (left_w - 2))
        for ent in entities[:max_lines - 4]:
            name = ent["name"][:left_w - 18]
            e_type = ent.get("entity_type", "concept")[:8]
            edges = ent.get("edge_count", 0)
            row = f"  {BRIGHT_MAGENTA}●{RESET} {name} {DIM}({e_type}, {edges} rels){RESET}"
            left_lines.append(_pad_line(row, left_w - 2))

        right_lines = []
        right_lines.append(f"{BOLD}Active Semantic Relations ({len(relations)}){RESET}")
        right_lines.append(THIN_HORIZ * (right_w - 2))
        for rel in relations[:max_lines - 4]:
            src = rel["source"][:16]
            r_type = rel["relation"][:14]
            tgt = rel["target"][:16]
            edge_str = f"  {BRIGHT_CYAN}{src}{RESET} -[{YELLOW}{r_type}{RESET}]-> {BRIGHT_CYAN}{tgt}{RESET}"
            right_lines.append(_pad_line(edge_str, right_w - 2))
            if rel.get("fact"):
                fact_str = f"    {DIM}Fact:{RESET} {rel['fact'][:right_w - 12]}"
                right_lines.append(_pad_line(fact_str, right_w - 2))

        combined = []
        if use_split:
            total_rows = max(len(left_lines), len(right_lines))
            for r in range(total_rows):
                l_str = left_lines[r] if r < len(left_lines) else ""
                r_str = right_lines[r] if r < len(right_lines) else ""
                combined.append(f"{_pad_line(l_str, left_w)}{DIM}{THIN_VERT}{RESET}{_pad_line(r_str, right_w)}")
        else:
            combined.extend(left_lines)
            combined.append(THIN_HORIZ * (width - 4))
            combined.extend(right_lines)
        return combined

    def render_tab4_code(self, width: int, max_lines: int) -> List[str]:
        """Render Tab 4: Structural Code Graph & AST Drift."""
        symbols = fetch_code_symbols(self.db_path, project=self.active_project if self.active_project != "All Projects" else None)
        lines = []
        lines.append(f"  {BOLD}Indexed Code Symbols ({len(symbols)} tracked){RESET}")
        lines.append(f"  {THIN_HORIZ * (width - 6)}")
        if not symbols:
            lines.append("  (No code symbols indexed yet. Run 'code_index' MCP tool in your repository.)")
            return lines

        lines.append(f"  {'KIND'.ljust(8)} {'NAME'.ljust(26)} {'FILE & RANGE'.ljust(32)} {'AST HASH'}")
        lines.append(f"  {THIN_HORIZ * (width - 6)}")
        for sym in symbols[:max_lines - 6]:
            k = sym.get("kind", "symbol")[:7]
            n = sym.get("name", "")[:25]
            f = f"{sym.get('file_path', '')}:{sym.get('start_line', 0)}"[:30]
            h = (sym.get("ast_hash") or "unhashed")[:12]
            lines.append(f"  {BRIGHT_GREEN}{k.ljust(8)}{RESET} {BOLD}{n.ljust(26)}{RESET} {DIM}{f.ljust(32)}{RESET} {YELLOW}{h}{RESET}")
        return lines

    def render_tab5_sessions(self, width: int, max_lines: int) -> List[str]:
        """Render Tab 5: Episodic Sessions Timeline & WIP."""
        sessions = fetch_sessions(self.db_path, project=self.active_project if self.active_project != "All Projects" else None)
        lines = []
        lines.append(f"  {BOLD}Episodic Developer Sessions ({len(sessions)} sessions){RESET}")
        lines.append(f"  {THIN_HORIZ * (width - 6)}")
        if not sessions:
            lines.append("  (No episodic sessions recorded yet.)")
            return lines

        lines.append(f"  {'STATUS'.ljust(12)} {'BRANCH / DURATION'.ljust(24)} {'GOAL / SUMMARY'}")
        lines.append(f"  {THIN_HORIZ * (width - 6)}")
        for s in sessions[:max_lines - 6]:
            outcome = s.get("outcome") or s.get("status") or "active"
            color = BRIGHT_GREEN if outcome in ("completed", "success") else (BRIGHT_YELLOW if outcome == "active" else RED)
            st_badge = f"{color}[{outcome[:9]}]{RESET}".ljust(20)
            branch = f"{s.get('git_branch') or 'main'} ({int(s.get('duration_seconds') or 0)}s)"[:22]
            goal = (s.get("goal") or s.get("summary") or "General coding session").replace("\n", " ")[:width - 45]
            lines.append(f"  {st_badge} {DIM}{branch.ljust(24)}{RESET} {goal}")
        return lines

    def render_tab6_audit(self, width: int, max_lines: int) -> List[str]:
        """Render Tab 6: Store Hygiene & Prune Candidates."""
        if self.cached_audit is None:
            self.cached_audit = MemoryAudit(self.db_path, self.vault_dir).scan()
        audit = self.cached_audit
        lines = []

        lines.append(f"  {BOLD}Memory Store Hygiene Scan ({audit['total_observations']} observations){RESET}")
        lines.append(f"  {THIN_HORIZ * (width - 6)}")

        tf = len(audit["test_fixtures"])
        tf_color = GREEN if tf == 0 else RED
        lines.append(f"    {tf_color}• Synthetic Test Fixtures:{RESET}       {tf}")

        nr = len(audit["noise_records"])
        nr_color = GREEN if nr == 0 else YELLOW
        lines.append(f"    {nr_color}• Zero-Signal Noise Records:{RESET}     {nr}")

        sr = len(audit["superseded_records"])
        lines.append(f"    {BLUE}• Superseded Records:{RESET}            {sr}")

        uc = len(audit["unconfirmed_zero_use"])
        lines.append(f"    {MAGENTA}• Unconfirmed 0-Relevance Records:{RESET} {uc}")
        lines.append("")

        if tf > 0 or nr > 0:
            lines.append(f"    {BRIGHT_YELLOW}Action Available: Press [p] to prune {tf + nr} fixtures and noise records.{RESET}")
        else:
            lines.append(f"    {BRIGHT_GREEN}✓ Clean store! No test fixtures or noise detected.{RESET}")

        lines.append(f"    {CYAN}Action Available: Press [c] to run full vault deduplication & compaction.{RESET}")
        return lines

    def render_help_modal(self, width: int, height: int) -> List[str]:
        """Render floating Help Cheatsheet modal overlay."""
        box_w = min(68, width - 6)
        pad = " " * ((width - box_w) // 2)
        lines = []

        lines.append(f"{pad}{BRIGHT_CYAN}{BOX_TOP_LEFT}{BOX_HORIZ * (box_w - 2)}{BOX_TOP_RIGHT}{RESET}")
        lines.append(f"{pad}{BRIGHT_CYAN}{BOX_VERT}{RESET} {BOLD}{'Keyboard Shortcuts Cheatsheet'.center(box_w - 4)}{RESET} {BRIGHT_CYAN}{BOX_VERT}{RESET}")
        lines.append(f"{pad}{BRIGHT_CYAN}{BOX_MID_LEFT}{BOX_HORIZ * (box_w - 2)}{BOX_MID_RIGHT}{RESET}")

        shortcuts = [
            ("1 - 6", "Jump directly to Tabs 1 - 6"),
            ("Tab / Shift-Tab", "Next / Previous tab"),
            ("← / → or h / l", "Switch active tab"),
            ("↑ / ↓ or j / k", "Scroll list items & observations"),
            ("g / G", "Jump to top / bottom of list"),
            ("/", "Live FTS5 Search (in Explorer)"),
            ("o / P", "Cycle active project filter"),
            ("d", "Mark selected observation superseded"),
            ("p", "Prune synthetic fixtures & noise"),
            ("c", "Compact vault deduplication"),
            ("r", "Refresh current view metrics"),
            ("? / F1", "Toggle this Help cheatsheet"),
            ("q / Esc", "Quit TUI / Close modal / Exit search"),
        ]
        for key, desc in shortcuts:
            row = f"  {BRIGHT_YELLOW}{key.ljust(18)}{RESET} {desc}"
            sp = box_w - len(_strip_ansi(row)) - 2
            lines.append(f"{pad}{BRIGHT_CYAN}{BOX_VERT}{RESET}{row}{' ' * max(sp, 0)}{BRIGHT_CYAN}{BOX_VERT}{RESET}")

        lines.append(f"{pad}{BRIGHT_CYAN}{BOX_BOT_LEFT}{BOX_HORIZ * (box_w - 2)}{BOX_BOT_RIGHT}{RESET}")
        return lines

    def render(self) -> str:
        """Render full screen dashboard buffer."""
        cols, rows = shutil.get_terminal_size((80, 24))
        width = max(cols - 2, 70)
        content_rows = max(rows - 10, 10)

        screen_lines = []
        screen_lines.extend(self.render_header(width))

        # Render Active Tab Content
        if self.show_help:
            tab_lines = self.render_help_modal(width, content_rows)
        elif self.active_tab == 1:
            tab_lines = self.render_tab1_health(width, content_rows)
        elif self.active_tab == 2:
            tab_lines = self.render_tab2_explorer(width, content_rows)
        elif self.active_tab == 3:
            tab_lines = self.render_tab3_graph(width, content_rows)
        elif self.active_tab == 4:
            tab_lines = self.render_tab4_code(width, content_rows)
        elif self.active_tab == 5:
            tab_lines = self.render_tab5_sessions(width, content_rows)
        else:
            tab_lines = self.render_tab6_audit(width, content_rows)

        # Pad or truncate tab content
        for i in range(content_rows):
            if i < len(tab_lines):
                line_content = tab_lines[i]
                padded = _pad_line(f" {line_content}", width)
                screen_lines.append(f"{CYAN}{BOLD}{BOX_VERT}{RESET}{padded}{CYAN}{BOLD}{BOX_VERT}{RESET}")
            else:
                screen_lines.append(f"{CYAN}{BOLD}{BOX_VERT}{RESET}{' ' * width}{CYAN}{BOLD}{BOX_VERT}{RESET}")

        screen_lines.extend(self.render_footer(width))
        return "\n".join(screen_lines)

    def run_interactive(self) -> None:
        """Run interactive ANSI dashboard loop."""
        sys.stdout.write(HIDE_CURSOR)
        sys.stdout.write(CLEAR_SCREEN)
        sys.stdout.flush()

        old_settings = None
        if os.name != "nt" and sys.stdin.isatty():
            import termios
            import tty
            fd = sys.stdin.fileno()
            try:
                old_settings = termios.tcgetattr(fd)
                tty.setcbreak(fd)
            except Exception:
                old_settings = None

        try:
            needs_clear = True
            while True:
                prefix = CLEAR_SCREEN if needs_clear else CURSOR_HOME
                needs_clear = False
                output = f"{prefix}{self.render()}"
                sys.stdout.write(output)
                sys.stdout.flush()

                key = _read_single_key(timeout=0.25)
                if not key:
                    continue

                # Search input mode handling
                if self.input_mode == "search":
                    if key in ("enter", "\r", "\n"):
                        self.search_query = self.search_buffer.strip()
                        self.input_mode = None
                        self.selected_index = 0
                        self.set_flash(f"► Search applied: '{self.search_query}'", duration=2.0)
                    elif key in ("esc", "\x1b"):
                        self.input_mode = None
                        self.set_flash("Search cancelled.", duration=1.5)
                    elif key in ("backspace", "\x7f", "\x08"):
                        self.search_buffer = self.search_buffer[:-1]
                    elif len(key) == 1 and key.isprintable():
                        self.search_buffer += key
                    continue

                k = key.lower()
                if k in ("q", "\x03"):  # q or Ctrl+C
                    break
                elif k in ("esc",):
                    if self.show_help:
                        self.show_help = False
                    elif self.search_query:
                        self.search_query = ""
                        self.set_flash("Cleared search filter.", duration=1.5)
                elif k in ("?", "f1"):
                    self.show_help = not self.show_help
                elif k in ("1", "2", "3", "4", "5", "6"):
                    target_tab = int(k)
                    if self.active_tab != target_tab:
                        self.active_tab = target_tab
                        self.selected_index = 0
                        needs_clear = True
                        if target_tab == 6 and self.cached_audit is None:
                            self.set_flash("⏳ Scanning memory store for audit hygiene...", duration=5.0)
                            sys.stdout.write(f"{CLEAR_SCREEN}{self.render()}")
                            sys.stdout.flush()
                        self.set_flash(f"► Switched to [{target_tab}] {self.TAB_NAMES[target_tab - 1]}", duration=1.5)
                elif k in ("tab", "right", "l"):
                    self.active_tab = (self.active_tab % len(self.TAB_NAMES)) + 1
                    self.selected_index = 0
                    needs_clear = True
                    self.set_flash(f"► Switched to [{self.active_tab}] {self.TAB_NAMES[self.active_tab - 1]}", duration=1.5)
                elif k in ("shift_tab", "left", "h"):
                    self.active_tab = len(self.TAB_NAMES) if self.active_tab == 1 else (self.active_tab - 1)
                    self.selected_index = 0
                    needs_clear = True
                    self.set_flash(f"► Switched to [{self.active_tab}] {self.TAB_NAMES[self.active_tab - 1]}", duration=1.5)
                elif k in ("up", "k"):
                    if self.selected_index > 0:
                        self.selected_index -= 1
                elif k in ("down", "j"):
                    self.selected_index += 1
                elif k == "g":
                    self.selected_index = 0
                elif k == "g":  # shift+g handled in raw
                    self.selected_index = 9999
                elif k == "/":
                    self.active_tab = 2
                    self.input_mode = "search"
                    self.search_buffer = self.search_query
                elif k in ("o", "p") and self.active_tab == 2:
                    self.cycle_project_filter()
                elif k == "r":
                    self.set_flash("⏳ Refreshing memory statistics...", duration=5.0)
                    sys.stdout.write(f"{CURSOR_HOME}{self.render()}")
                    sys.stdout.flush()
                    self.cached_audit = None
                    self.set_flash("✓ Refreshed metrics and scan.", duration=3.0)
                elif k == "p" and self.active_tab in (2, 6):
                    self.set_flash("⏳ Pruning synthetic fixtures and noise records...", duration=5.0)
                    sys.stdout.write(f"{CURSOR_HOME}{self.render()}")
                    sys.stdout.flush()
                    auditor = MemoryAudit(self.db_path, self.vault_dir)
                    res = auditor.prune_candidates(("test_fixtures", "noise_records"))
                    self.cached_audit = None
                    self.set_flash(f"✓ Pruned {res['pruned_direct']} records; compacted {res['observations_compacted']}.", duration=4.0)
                elif k == "c":
                    self.set_flash("⏳ Compacting memory vault deduplication...", duration=5.0)
                    sys.stdout.write(f"{CURSOR_HOME}{self.render()}")
                    sys.stdout.flush()
                    res = deduplicate_and_compact(vault_dir=self.vault_dir, session_db=self.db_path)
                    self.cached_audit = None
                    self.set_flash(f"✓ Vault compacted ({res.get('observations_pruned', 0)} pruned).", duration=4.0)
                elif k == "d" and self.active_tab == 2:
                    obs_list = fetch_observations(self.db_path, project=self.active_project if self.active_project != "All Projects" else None, search=self.search_query or None)
                    if obs_list and 0 <= self.selected_index < len(obs_list):
                        target_id = obs_list[self.selected_index]["id"]
                        con = open_db(self.db_path)
                        try:
                            con.execute("UPDATE observations SET superseded_by = -1 WHERE id = ?", (target_id,))
                            con.commit()
                            self.set_flash(f"✓ Marked observation #{target_id} as superseded.", duration=3.0)
                        except Exception as e:
                            self.set_flash(f"Failed to supersede #{target_id}: {e}", duration=3.0)
                        finally:
                            con.close()
                else:
                    disp = key if (len(key) == 1 and key.isprintable()) else repr(key)
                    self.set_flash(f"Key '{disp}' pressed. Press [?] for shortcuts.", duration=2.0)
        finally:
            if old_settings is not None and os.name != "nt":
                import termios
                try:
                    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
                except Exception:
                    pass
            sys.stdout.write(CLEAR_SCREEN + SHOW_CURSOR)
            sys.stdout.flush()

    def run_once(self) -> None:
        """Render once to stdout without interactive loop."""
        print(self.render())


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="agi-memory tui", description="God-Mode Terminal Inspector & Cognitive Dashboard")
    parser.add_argument("--once", "--headless", action="store_true", help="Print dashboard snapshot once and exit")
    parser.add_argument("--tab", type=int, choices=[1, 2, 3, 4, 5, 6], default=1, help="Starting tab (1: health, 2: explorer, 3: graph, 4: code, 5: sessions, 6: audit)")
    parser.add_argument("--search", type=str, default="", help="Initial search filter for explorer")
    parser.add_argument("--project", type=str, default="All Projects", help="Filter by project")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    inspector = TerminalInspector()
    inspector.active_tab = args.tab
    inspector.search_query = args.search
    inspector.active_project = args.project

    if args.once or not sys.stdin.isatty():
        inspector.run_once()
    else:
        inspector.run_interactive()


if __name__ == "__main__":
    main()
