# Memory Discipline

When working in this project:
1. Always call `memory_recall` or `memory_recall_deep` with the project name before making assumptions about architecture, conventions, or past fixes.
2. Call `memory_record` whenever settling a pattern, convention, or resolving a non-trivial issue.
3. Call `memory_session_outcome` before you finish when work was dropped, blocked or
   replaced. An unmarked session is recorded as `unknown` and the next session is told
   not to resume it -- marking it is how that noise turns into a real signal.
4. Keep `CLAUDE.md` compact; let `agent-memory` handle durable learnings.
