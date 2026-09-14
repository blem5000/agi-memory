# Canonical Vault & Cross-Device Git Sync

`agi-memory` completely separates **framework code** from your **memory data**:
- **Framework Updates**: You can `git pull`, `brew upgrade agi-memory`, or `pip install -U agi-memory` anytime without ever risking or modifying your memories.
- **Canonical Vault (`~/.agi-memory/vault/`)**: Your memories are stored as merge-friendly, append-only JSONL files (`observations.jsonl` and `graph.jsonl`). The vault ships a `.gitattributes` marking `*.jsonl merge=union`, so two machines that both appended between syncs merge by taking both sides instead of conflicting — the common case for append-only files — and the dedupe pass afterwards removes any line union reintroduced. An existing `~/.agent-memory/` from an earlier install is used in place of `~/.agi-memory/`.
- **Local Fast SQLite Cache (`~/.agi-memory/memory.db`)**: Automatically materialized and updated from the vault for sub-millisecond BM25 and recursive graph traversal.
- **Automatic Background Sync (`agi-sync`)**: While `auto_sync` is on (the default; set `"auto_sync": false` in `sync.json` to turn it off), every `record` and `add_edge` schedules a 3-second debounced background sync, so a burst of writes syncs once, and the `session-end` hook forces one on the way out. None of it blocks the assistant. **Until a remote exists the vault only commits locally** — `agi-sync status` reports `no_remote`, and nothing has left the machine.
- **Periodic Deduplication & Compaction**: Prunes noise, duplicate observations, and redundant graph edges so your vault stays compact and performant over months of usage. It runs weekly or after 50 new memories, never on a fresh store's first sync, and rebuilds only the tables the vault carries (observations and graph) in a single transaction. Pinned blocks, curated aliases, session history and the code graph are left untouched, and an interrupted compaction leaves the previous rows rather than an empty table.

### 1-Command Setup (with GitHub CLI)
During `agi-integrate install all`, the installer automatically detects `gh` CLI:
```text
[✓] GitHub CLI (gh) detected: Logged in as @username
Create private GitHub repo 'agent-memory-vault' and enable automatic sync? [Y/n]: 
```
Pressing **Enter** creates your private repo and activates automatic cross-device sync.

### Sync CLI Commands
```bash
# Check vault sync status & diagnostics
agi-sync status

# Trigger immediate pull & push
agi-sync now

# Force deduplication and compaction of memory files
agi-sync dedupe

# Connect to any existing Git remote manually
agi-sync init git@github.com:username/my-agi-memory-vault.git

# Or have the gh CLI create the private repo for you
agi-memory sync init --create-private [--repo-name agent-memory-vault]
```

### Before the First Push on an Established Vault
Every sync commits a fresh copy of `observations.jsonl`, so loose git objects
pile up long before anything packs them — one real vault sat at 746 MB of loose
objects for a 22 MB working tree. Pack it before the initial push:
```bash
git -C ~/.agi-memory/vault gc     # 746 MB -> 25 MB on that vault
```
Git repacks on its own as objects accumulate, so this is a one-time concern.

### What Leaves the Machine
The vault is your memories in full: every recorded decision, session summary
and file path, for every project. `sync init --create-private` creates a
**private** repo, but the content is then on someone else's disk — worth a scan
if you have ever recorded a credential into a memory.

---
