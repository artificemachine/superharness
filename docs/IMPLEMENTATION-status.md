# Implementation Status — All Audit Documents

> **Split-brain principle**: SQLite is the canonical source of truth. YAML is export-only.
> Reads go through `state_reader` (SQLite). Writes go through `state_writer` (SQLite).
> YAML files are regenerated from SQLite for human readability only — never read by the runtime.

## ✅ Completed

### SQLite-only regression (AUDIT-sqlite-only-regression.md)
| # | Fix | Status |
|---|------|--------|
| 1 | Default STATE_BACKEND → sqlite_only | ✅ |
| 2 | Remove _ensure_ingested() auto-migration | ✅ |
| 3 | SQLite errors loud, no silent YAML fallback | ✅ |
| 4 | Strip yaml_sync.py → no-op stubs | ✅ |
| 5 | CI test for SQLite-only enforcement | ✅ |
| 6 | `shux task create` writes to SQLite directly | ✅ |

### 9 bugs fixed
| Bug | Symptom |
|-----|---------|
| TaskRow missing `updated_at` | in_progress timeout never fired |
| _task_row_from_dict clobber | Export silently overwrote SQLite |
| Inbox mirror YAML→SQLite crash | Transactions silently rolled back |
| Dashboard status mappings | archived→todo, failed→todo |
| str(Path('.')) substring match | Every Claude process shown as agent |
| shux status stale item gap | stale=17 visible, no issue raised |
| Discussion inbox not cleaned | Orphans accumulated after close |
| archived_at missing from TaskRow | Lifecycle timestamps lost |
| Zombie user sessions in live stream | 22h stale PIDs displayed |

### Agent toolkit plan (6 iterations)
| # | Feature | Source |
|---|---------|--------|
| 1 | Tool-loop guardrails | Hermes |
| 2 | Handoff generator CLI | Pi |
| 3 | FTS5 recall (migration v6) | Hermes |
| 4 | JSONL event stream | Both |
| 5 | Adapter policy gates | Hermes |
| 6 | Skill metrics + dashboard panel | Hermes |

### Other fixes
- `todo` lifecycle rule (120m → archive)
- `shux status` with 10 issue types + `--fix` + `--check` CI mode
- Discussion panel: submissions, timeline, live agents
- Discussion auto-consensus → auto-task (only for actionable points)
- Auto-enqueue skips expired deadlines
- Active state inbox invariant
- Undispatchable agent auto-cancel
- opencode added as valid owner
- `.superharness/state.sqlite3*` + `events.jsonl` added to `.gitignore` (inner + onboard)
- Panels: activity feed, ledger, out.log uncollapsed. err.log, skill insights collapsed.
- done/failed tasks hidden by default in contract tasks panel

---

## ❌ Remaining

### Split-brain: fully closed ✅
All YAML runtime read/write paths eliminated. YAML is export-only.

| Issue | Status |
|-------|--------|
| `_export_contract_yaml` still writes contract.yaml | ✅ No-op in sqlite_only |
| `_export_inbox_yaml` still writes inbox.yaml | ✅ No-op in sqlite_only |
| `shux discuss start` writes state.yaml to disk | ✅ SQLite also written |
| Dashboard discussion count reads from filesystem | ✅ Reads from SQLite |
| Test mode reads YAML first | ✅ By design (YAML fixtures) |
| `_yaml_writes_enabled` in inbox_watch.py | ✅ Gated by is_sqlite_only |

### High priority (from plans)
| Source | Feature | Effort | Blocked? |
|--------|---------|--------|----------|
| Protocol plan | `CONTRACT.md` ↔ SQLite Markdown sync | 1-2 days | No — SQLite is SoT, Markdown is export/view layer only |
| Protocol plan | MCP server for superharness state | 1 day | No — agents call MCP tools instead of `shux` CLI commands |

> **Note**: Both are now UX improvements, not architectural fixes.
> Split-brain is closed. Markdown sync = friendlier export format.
> MCP server = native protocol instead of shell commands.

### Medium priority
| Source | Feature |
|--------|---------|
| Hermes | `shux skills curate` lifecycle |
| Hermes | `shux insights --days 30` |
| Pi Mono | `shux packs` extension model |
| Pi Mono | Structured compaction summaries |
| Browser-harness | Self-healing mutation skill |
| Protocol plan | Shadow proxy (auto-ledger) |
| Protocol plan | Git-native state (commit hook) |

### Low priority
| Source | Feature |
|--------|---------|
| Hermes | ACP adapter |
| Hermes | Remote model catalog |
| Paperclip | 7+ adapter family |
| Paperclip | Plugin SDK |
