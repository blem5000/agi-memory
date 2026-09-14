# Memory Discipline

When working in this project:
1. Always call `memory_recall` or `memory_recall_deep` with the project name before making assumptions about architecture, conventions, or past fixes.
2. Call `memory_record` whenever settling a pattern, convention, or resolving a non-trivial issue.
   Pass `rationale` with it: a decision recorded without its reasoning arrives in every later
   session as settled fact, and nothing can re-examine it when the constraints change.
3. Pass `origin="user-confirmed"` only when the user actually stated or approved it.
   Everything you concluded yourself is `agent-inferred`, however confident -- the
   distinction is what lets a later session tell a decision from a guess, and it is
   worthless if inflated.
4. Call `memory_session_outcome` before you finish when work was dropped, blocked or
   replaced. An unmarked session is recorded as `unknown` and the next session is told
   not to resume it -- marking it is how that noise turns into a real signal.
5. Keep `CLAUDE.md` compact; let `agent-memory` handle durable learnings.
