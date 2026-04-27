# Inbox Queue Unification — Options

**Problem**: The "inbox dispatch queue" only shows watcher-dispatched tasks. Work that runs
outside the inbox (discussion rounds, CLI-dispatched sessions) shows as `in_progress` in
the task board but is invisible in the queue. Users see a count mismatch and can't find
the active work.

---

## Option A — Merge discussions into the queue panel (dashboard-only) ✅ SHIPPED in v1.37.3

Show discussion rounds inline in the inbox dispatch queue with a distinct `discussion` badge.
Same panel, different row type. Relevant actions: View, Cancel.

- **Scope**: `dashboard-ui.py` only — reads `.superharness/discussions/*/state.yaml`
- **Effort**: Small
- **Pros**: Eliminates confusion immediately, no protocol changes
- **Cons**: Queue panel becomes a mixed view, not a true unified model

---

## Option B — "Active work" section (new panel)

New panel above the queue that aggregates:
- Inbox items (pending, launched, running)
- Discussion rounds (in_progress, consensus)
- Running agent PIDs (from heartbeat / launched_at)

One "what is happening right now" view. Queue panel stays for dispatch management.

- **Scope**: `dashboard-ui.py` — new HTML section + data endpoint
- **Effort**: Medium
- **Pros**: Clean separation — "active now" vs "queued"
- **Cons**: Two panels to understand instead of one

---

## Option C — Unified session model (architectural)

Make `shux discuss` write an inbox-style item when it starts, so every unit of agent
work flows through one system. Discussions become first-class inbox citizens with
status tracking, retry, heartbeat, and remove — just like regular tasks.

- **Scope**: `shux discuss` command + inbox DAO + watcher + dashboard
- **Effort**: Large
- **Pros**: Single source of truth, consistent UX, enables watcher to manage discussions
- **Cons**: Requires protocol changes, backwards-compat for existing discussion state files

---

## Recommended path

1. **Now**: Option A — fast, dashboard-only, ships the fix
2. **Later**: Option C — proper architecture, discussions as first-class inbox items
3. **Skip B**: Option A + C together make B redundant
