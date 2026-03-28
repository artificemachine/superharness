# Session Handoff — 2026-03-27

**Stopped at:** 2026-03-27 ~17:05 UTC
**Session focus:** Superharness hardening plan (R1–R5 architecture review recommendations)

---

## Completed This Session

| Task | Status | Notes |
|------|--------|-------|
| `harden.R1-schema` | ✅ done | Pydantic v2 schemas for all 5 protocol YAML types. 24/24 tests pass. |
| `harden.R2-locks` | ✅ done | Stale-lock detection with PID + age-based auto-break. 28/28 tests pass. |
| `fix.watcher-env-snapshot` | ✅ done | `engine/env_snapshot.py` captures API keys at install, merges at dispatch. 13/13 tests pass. |
| `harden.R4-repair` | ✅ done | `hygiene --repair` flag with `_repair_create_handoff`, `_repair_append_ledger`, `_repair_fix_stuck_status`. 20/20 tests pass. |

---

## Paused / Pending

### `harden.R3-models` — Externalize model mappings to YAML
- **Owner:** codex-cli
- **Contract status:** `plan_approved`
- **Inbox:** paused (`id: 20260327T170425Z-harden.R3-models-86667-135830`)
- **History:** Failed twice (SDK crash → CLI fallback → 300s timeout at ~268K tokens). Codex ran but timed out before writing handoff.
- **Action next session:** Resume inbox item (set status `pending`) or re-enqueue fresh. Consider raising `--launcher-timeout` to 600s for this task. Files to create: `src/superharness/engine/models.yaml`, modify `model_router.py` + `sdk_runner.py` + `pyproject.toml`.

### `harden.R5-scaling-docs` — Document scaling limits
- **Owner:** codex-cli
- **Contract status:** `plan_approved`
- **Inbox:** paused (`id: 20260327T164829Z-harden.R5-scaling-docs-57542-d32f5d`)
- **History:** Just dispatched before session was paused — unknown progress.
- **Action next session:** Resume inbox item (set status `pending`). Files to modify: `protocol/spec.md`, `docs/ARCHITECTURE.md`, `README.md`.

---

## Bugs Fixed This Session (monitor-ui.py)

| Bug | Fix |
|-----|-----|
| `UnboundLocalError: webbrowser` — monitor crashed on start | Removed redundant `import webbrowser` inside `if` block (shadowed top-level import) |
| "Verify & Close" button failed for codex-cli-owned tasks | Added `--actor owner` to the `close` subprocess call in the backend handler |
| Task IDs with `/` (e.g. discussion round tasks) broke path construction | Added `safe_task_id = task_id.replace("/", "_")` before file write |
| Ghost discussion task `discuss-.../round-1` blocked UI | Removed from `contract.yaml`; was a discussion artifact with no real work |

---

## Watcher Issues Fixed This Session

| Issue | Fix |
|-------|-----|
| Watcher not loading (`level=bad`) | Fixed `scripts_dir` in `watcher_worker.py` to use `importlib.resources` instead of hardcoded path |
| Watcher heartbeat stale (8–10m) | Stale lock at `/tmp/superharness-inbox-watch-*.lock` (no PID file, 10.5m old) — removed manually |
| `review_requested` tasks had no UI action buttons | Added "Verify & Close" and "Reject" buttons + backend handlers in `monitor-ui.py` |

---

## Current Contract Summary

```
done          : R1-schema, R2-locks, R4-repair, fix.watcher-env-snapshot  (+ all earlier tasks)
paused/pending: R3-models (codex-cli), R5-scaling-docs (codex-cli)
review needed : harden.R4-repair → click "Verify & Close" in monitor UI
```

---

## How to Resume Next Session

1. **Open monitor UI:** `shux monitor --project /Users/airm2max/DevOpsSec/superharness`
2. **Verify & Close `harden.R4-repair`** via the UI button (status: `done`, awaiting owner review)
3. **Resume R3 and R5:**
   ```python
   # Set paused items back to pending
   python3 -c "
   import yaml
   path = '/Users/airm2max/DevOpsSec/superharness/.superharness/inbox.yaml'
   with open(path) as f: inbox = yaml.safe_load(f)
   items = inbox if isinstance(inbox, list) else inbox.get('items', [])
   for i in items:
       if i.get('status') == 'paused':
           i['status'] = 'pending'
           print('resumed:', i.get('task'))
   with open(path, 'w') as f: yaml.dump(inbox, f, default_flow_style=False)
   "
   ```
4. **Watch for R3 timeout:** If codex times out again on R3-models, raise launcher timeout:
   - Re-install watcher: `watcher-worker --project . --launcher-timeout 600`
5. **Run full test suite** after R3/R5 complete: `pytest tests/ -q` (target: ~1,012 tests)

---

## Known Recurring Issues

- **Watcher stale lock:** If heartbeat goes stale >8m, check `/tmp/superharness-inbox-watch-*.lock` — remove if no owning process: `rm -rf /tmp/superharness-inbox-watch-*.lock`
- **R3-models timeout:** Task is large (model_router.py + sdk_runner.py + models.yaml + 12+ tests). 300s may not be enough for codex. Raise to 600s.
- **SDK fallback:** Codex SDK frequently fails (`Fatal error in message reader`) and falls back to CLI — normal behaviour, not a bug.
