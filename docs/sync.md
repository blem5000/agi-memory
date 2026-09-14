# Canonical Vault & Cross-Device Git Sync

`agi-memory` completely separates **framework code** from your **memory data**:
- **Framework Updates**: You can `git pull`, `brew upgrade agi-memory`, or `pip install -U agi-memory` anytime without ever risking or modifying your memories.
- **Canonical Vault (`~/.agi-memory/vault/`)**: Your memories are stored as merge-friendly, append-only JSONL files (`observations.jsonl` and `graph.jsonl`). Git handles merging across multiple laptops and desktops seamlessly with zero binary merge conflicts.
- **Local Fast SQLite Cache (`~/.agi-memory/memory.db`)**: Automatically materialized and updated from the vault for sub-millisecond BM25 and recursive graph traversal.
- **Automatic Background Sync (`agi-sync`)**: Whenever an observation or pattern is recorded, `agi-memory` automatically commits and pushes in the background without blocking the AI assistant.
- **Periodic Deduplication & Compaction**: Prunes noise, duplicate observations, and redundant graph edges so your vault stays compact and performant over months of usage.

### 1-Command Setup (with GitHub CLI)
During `agi-integrate install all`, the installer automatically detects `gh` CLI:
```text
[✓] GitHub CLI (gh) detected: Logged in as @username
Create private GitHub repo 'agi-memory-vault' and enable automatic sync? [Y/n]: 
```
Pressing **Enter** creates your private repo and activates automatic cross-device sync.

### Sync CLI Commands
```bash
# Check vault sync status & diagnostics
agi-sync status

# Trigger immediate pull & push
agi-sync sync

# Force deduplication and compaction of memory files
agi-sync dedupe

# Connect to any existing Git remote manually
agi-sync init git@github.com:username/my-agi-memory-vault.git
```

### Automatic freshness checks

The client checks whether a sync is needed without being asked:

- **`session-start` hook / MCP `initialize`** call `ensure_fresh_background()`:
  it returns the last-known status instantly and, at most once per
  `AGI_MEMORY_SYNC_CHECK_INTERVAL` (default 900s), spawns a *detached*
  background process that fetches, pulls when behind (rebase + re-import)
  and pushes when ahead. A detached process (not a thread) because hooks
  and CLIs exit too fast for a thread to finish.
- When the vault is behind/ahead, the startup context gains a `## Vault Sync`
  line telling the agent a background sync is running.
- `memory_sync` (`action: status`), `agi-integrate sync status` and
  `agi-sync status` report cached `behind` / `ahead` counts — no network
  involved. `sync.py check` forces a one-shot check.

```bash
AGI_MEMORY_SYNC_CHECK_INTERVAL=300  # check at most every 5 minutes (0 disables)
AGI_MEMORY_SYNC_FETCH_TIMEOUT=10    # seconds per fetch attempt
AGI_MEMORY_SYNC_CONFIG_FILE=~/.agi-memory/sync.json  # config override (tests)
```

---
