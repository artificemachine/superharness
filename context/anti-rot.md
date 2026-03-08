# Anti-Rot Protocol — DEPRECATED

**This file is no longer maintained.**

The SessionStart hook in `adapters/claude-code/hooks/session-start.sh` re-injects identity and protocol context on every session start, resume, clear, and compact. This solves the context rot problem at the infrastructure level.

For session continuity, see:
- `state/state-protocol.md` — progress files and handoff format
- `.superharness/ledger.md` — append-only activity log that survives compaction
- `adapters/claude-code/hooks/session-start.sh` — re-injection mechanism
