# Remove contract.yaml as a Live Dependency

Status: scoped, not started
Date: 2026-05-07

## Problem

contract.yaml and SQLite are both sources of truth for task state, but they
drift because multiple code paths write to one without updating the other.

Example: claude-code agent completed `feat.dashboard-auto-restart-on-upgrade`,
directly edited contract.yaml to `status: done`. SQLite still has `plan_approved`.
The auto-enqueue loop reads SQLite, sees an actionable task, spawns dispatches
that immediately fail (work is already done). 294 dispatch failures and counting.

`write_contract` and `read_contract` in `contract_io.py` already handle
sqlite_only mode correctly. The problem is that ~15 call sites bypass them
entirely and touch the YAML file directly.

## End State

- SQLite is the sole source of truth for task state
- contract.yaml is an export artifact only (regenerated on demand via `shux export-yaml`)
- Zero production code reads or writes contract.yaml directly
- Agent adapter templates instruct agents to use `shux` CLI, not raw YAML edits

---

## Scope

### Layer 1 - Direct writes that skip SQLite (3 sites)

These are desync factories. Each mutates contract.yaml without touching SQLite.

| # | Site | What it does | Fix |
|---|------|-------------|-----|
| 1 | `engine/discuss.py:216` | `_atomic_write(contract_file, yaml.dump(contract_doc))` | Route through `contract_io.write_contract` |
| 2 | `commands/onboard.py:349` | `contract_file.write_text(yaml.dump(doc))` | Route through `contract_io.write_contract` |
| 3 | `adapters/claude-code/hooks/session-stop.sh:188` | Opens contract.yaml, mutates `status: stopped`, writes back with `open(path, "w")` | Call `shux task status --status stopped` via CLI, or use `state_writer` |

### Layer 2 - Direct reads that skip state_reader (9 sites)

These read stale data when SQLite has diverged from the YAML file.

| # | Site | Current | Fix |
|---|------|---------|-----|
| 4 | `scripts/dashboard-ui.py:1206,1619,1667,+1` | `yaml.safe_load(contract_file.read_text())` | Use `state_reader.get_contract_doc()` or existing `/api` endpoint |
| 5 | `adapters/claude-code/hooks/session-start.sh:30,70` | `yaml.safe_load(open('contract.yaml'))` + raw `open().read()` | Use `shux contract` / `shux context` CLI |
| 6 | `adapters/claude-code/hooks/session-stop.sh:38` | `yaml.safe_load(open('contract.yaml'))` | Use `shux context` |
| 7 | `engine/preflight.py:154` | `yaml.safe_load(Path(contract_file).read_text())` | Use `state_reader.get_contract_doc()` |
| 8 | `engine/recall.py:109` | `yaml.safe_load(contract_path.read_text())` | Use `state_reader.get_tasks()` |
| 9 | `commands/handoff_write.py:88,116` | `yaml.safe_load(contract_file.read_text())` | Use `state_reader.get_task()` |
| 10 | `commands/onboard.py:333` | `yaml.safe_load(contract_file.read_text())` | Use `state_reader.get_contract_doc()` |
| 11 | `commands/recap.py:96` | `yaml.safe_load(contract_file.read_text())` | Use `state_reader.get_tasks()` |
| 12 | `commands/inbox_watch.py:41` | YAML fallback in `_load_tasks` (dead code when sqlite_only) | Remove the YAML fallback path |

### Layer 3 - Agent adapter templates (6 files)

These instruct agents to directly read or write contract.yaml. Agents follow
these instructions literally - so they bypass `contract_io` and create desyncs
every time they update task status.

| # | File | Current text | New text |
|---|------|-------------|----------|
| 13 | `claude-code/CLAUDE.md.template:14` | "Read `contract.yaml` before starting any work." | "Run `shux contract` to see all tasks. Run `shux context <id>` for full task context." |
| 14 | `claude-code/CLAUDE.md.template:20` | "update contract status" | "Run `shux task status --id <id> --status <new-status>` to advance a task. Run `shux close <id>` to mark it done." |
| 15 | `claude-code/CLAUDE.md.template:26` | "Read `.superharness/contract.yaml`." | "Run `shux contract`." |
| 16 | `codex-cli/AGENTS.md.template:24` | "Read `contract.yaml` before starting any work." | "Run `shux contract` to see all tasks." |
| 17 | `codex-cli/AGENTS.md.template:36` | "Read `.superharness/contract.yaml`." | "Run `shux contract`." |
| 18 | `session-start.sh:191` | "read contract.yaml, failures.yaml, decisions.yaml, and any handoffs" | "run `shux contract`, `shux context`" |
| 19 | `scope-guard.sh:11` | Reads contract.yaml for task validation | Use `shux contract` or `state_reader` |

### Layer 4 - contract_io cleanup (1 site)

Once nothing else writes contract.yaml directly, the YAML write path in
`write_contract` becomes dead code and can be removed.

| # | Site | What | 
|---|------|------|
| 20 | `engine/contract_io.py:150-179` | The non-sqlite_only branch that writes YAML to disk. Already unreachable when `is_sqlite_only()` is true. Can be removed or gated behind an export-only flag. |

---

## Migration Order

### Phase A - Stop the bleeding (sites 1-3)
Fix the three direct writes. These are the only paths that create new
contract.yaml/SQLite desyncs. After this phase, contract.yaml only changes
when `write_contract` (in non-sqlite_only mode) writes it - which is zero
times in the default sqlite_only configuration.

### Phase B - Stop reading stale data (sites 4-12)
Fix the nine direct reads. After this phase, all production code routes
through `state_reader` and always sees SQLite as the source of truth.

### Phase C - Fix agent instructions (sites 13-19)
Update adapter templates and hooks. After this phase, agents use `shux` CLI
for all contract operations, which routes through `contract_io` and keeps
SQLite in sync.

### Phase D - Remove YAML write path (site 20)
With zero callers, remove the YAML write branch from `write_contract`.
contract.yaml is now purely an export artifact generated by `shux export-yaml`.

### Phase E - Canary (optional)
Rename `contract.yaml` to `contract.yaml.legacy` for one release. If nothing
breaks, delete it in the next release.

---

## What Does NOT Change

- **Tests** (~15 files write contract.yaml fixtures). Tests use YAML as a
  convenient fixture format. Production code reads from SQLite. This is fine
  as long as tests verify behavior against the SQLite path too.
- **`shux export-yaml`** continues to generate human-readable YAML snapshots
  from SQLite on demand.
- **pack/import** already handles both formats.

---

## Risk

- **Agent sessions during migration**: If an agent session is running with the
  old template (telling it to edit contract.yaml) while watcher is already
  reading from SQLite, new status changes will be invisible. Mitigation: ship
  template updates first, then fix reads, then fix writes.
- **Dashboard**: Dashboard reads contract.yaml directly in 4 places. If those
  switch to SQLite and SQLite is stale (from existing desyncs), dashboard
  shows wrong status. Mitigation: run `shux status --fix` and `shux inbox-gc`
  before deploying.
- **Rollback**: If contract.yaml is deleted and something still reads it,
  errors cascade. Mitigation: the canary phase (E) catches this.
