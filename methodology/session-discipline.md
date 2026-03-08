# Session Discipline — DEPRECATED

**This file is no longer maintained.**

Session discipline is now enforced through hooks, not documentation:

- **Scope guard** (`adapters/claude-code/hooks/scope-guard.sh`) — blocks writes to sensitive files, warns on out-of-scope modifications
- **Branch guard** (`adapters/claude-code/hooks/branch-guard.sh`) — blocks push to main, warns on destructive git operations
- **Ledger auto-append** (`adapters/claude-code/hooks/ledger-append.sh`) — automatically logs file changes
- **Contract scope** — tasks are assigned in `contract.yaml`, agents stay in scope

The original session templates (evening 1-2 hrs, weekend 5-10 hrs) and anti-pattern guards are now encoded in `identity/core.md` which gets injected on every session start.

Key rules that survived:
- ONE task per evening session (in identity/core.md: "Ship > plan. One task per session.")
- Anti-patterns ranked: scope creep > over-planning > shiny object > skipping /upvault
- Planning happens at END, not start (start by reading contract, end by writing handoff)
