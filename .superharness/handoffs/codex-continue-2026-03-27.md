# Handoff for Codex — Continue superharness Hardening (2026-03-27)

**From:** claude-code (session ended 2026-03-27 ~17:30 UTC)
**To:** codex-cli
**Project:** `/Users/airm2max/DevOpsSec/superharness`
**Worker project:** `/Users/airm2max/.superharness-workers/superharness`

---

## What Was Completed (Do Not Redo)

| Task | Status | Summary |
|------|--------|---------|
| `harden.R1-schema` | ✅ done | Pydantic v2 models in `engine/schemas.py`. 24 tests. |
| `harden.R2-locks` | ✅ done | `_MkdirLock` rewritten with PID + age-based stale detection. 28 tests. |
| `fix.watcher-env-snapshot` | ✅ done | `engine/env_snapshot.py` captures API keys at install, merges at dispatch. 13 tests. |
| `harden.R4-repair` | ✅ done | `hygiene --repair` flag in `validate.py`. 20 tests. |

**Total test suite after these: ~1,005 tests passing.**

---

## Your Two Tasks

### TASK 1 — `harden.R3-models` (priority: high)
**Externalize hardcoded model mappings to YAML config**

#### Problem
Two files have hardcoded model names and prices:

**`src/superharness/engine/model_router.py` lines 10-13:**
```python
MODEL_MAP: dict[str, dict[str, str]] = {
    "claude-code": {"mini": "haiku", "standard": "sonnet", "max": "opus"},
    "codex-cli": {"mini": "gpt-5.2", "standard": "gpt-5.3-codex", "max": "gpt-5.4"},
}
```

**`src/superharness/engine/sdk_runner.py` lines 23-27:**
```python
_MODEL_PRICING = {
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.25, "output": 1.25},
}
```

#### What to Build (TDD — RED → GREEN → REFACTOR)

**RED — write these failing tests first in `tests/unit/test_model_config.py`:**
1. `test_resolve_model_returns_haiku_baseline` — `resolve_model("claude-code", "mini")` returns `"haiku"` (no config file present)
2. `test_project_override_changes_model` — `.superharness/models.yaml` with `claude-code.mini: my-model` overrides the bundled default
3. `test_partial_override_preserves_others` — overriding only `claude-code.mini` keeps `codex-cli` mappings intact
4. `test_missing_config_falls_back_to_hardcoded` — deleting `models.yaml` falls back gracefully, no exception
5. `test_corrupt_config_falls_back` — invalid YAML in `models.yaml` falls back silently
6. `test_pricing_loads_from_yaml` — pricing dict loaded from `models.yaml` when present
7. `test_pricing_falls_back_to_hardcoded` — no `models.yaml` → hardcoded pricing unchanged
8. `test_deep_merge_preserves_unoverridden_keys` — project override merges at agent level, not replaces
9. `test_bundled_yaml_is_primary_source` — bundled `engine/models.yaml` used when no project override
10. `test_project_yaml_takes_precedence_over_bundled` — project file wins over bundled
11. `test_load_is_cached` — second call to `_load_model_map()` doesn't re-read disk (module-level cache)
12. `test_resolve_model_no_project_dir` — `resolve_model("claude-code", "standard")` works when called without project_dir arg

**GREEN — implement:**

1. **Create `src/superharness/engine/models.yaml`** (bundled defaults):
```yaml
model_map:
  claude-code:
    mini: haiku
    standard: sonnet
    max: opus
  codex-cli:
    mini: gpt-5.2
    standard: gpt-5.3-codex
    max: gpt-5.4

pricing:
  claude-opus-4-6:
    input: 15.00
    output: 75.00
  claude-sonnet-4-6:
    input: 3.00
    output: 15.00
  claude-haiku-4-5-20251001:
    input: 0.25
    output: 1.25
```

2. **Modify `src/superharness/engine/model_router.py`:**
   - Add `_load_model_map(project_dir=None)` function:
     - Load bundled `models.yaml` via `importlib.resources.files("superharness").joinpath("engine/models.yaml")`
     - Deep-merge project-level `.superharness/models.yaml` over bundled (agent-level merge)
     - Fall back to hardcoded `MODEL_MAP` on any error
     - Cache result at module level (`_cached_map`)
   - Update `resolve_model()` to call `_load_model_map(project_dir)` instead of using `MODEL_MAP` directly
   - Keep `MODEL_MAP` as the hardcoded fallback constant (don't delete it)

3. **Modify `src/superharness/engine/sdk_runner.py`:**
   - Add `_load_pricing(project_dir=None)` with same pattern (bundled YAML → project override → hardcoded fallback)
   - Update `_calculate_cost()` to use `_load_pricing(project_dir)` instead of `_MODEL_PRICING` directly
   - Keep `_MODEL_PRICING` as fallback

4. **Modify `pyproject.toml`:**
   - Add `engine/models.yaml` to package data so it's bundled with the package:
   ```toml
   [tool.setuptools.package-data]
   superharness = ["scripts/*", "engine/models.yaml", ...]
   ```

**REFACTOR:**
- Extract the load/deep-merge/cache pattern into a shared `_load_yaml_config(bundled_path, project_dir, project_filename, fallback)` helper in a new `engine/config_loader.py` or inline utility
- Both `_load_model_map` and `_load_pricing` should use it

#### Acceptance Criteria
- [ ] All model lookups work with no config file present (hardcoded fallback)
- [ ] Bundled `engine/models.yaml` is the primary source
- [ ] Per-project `.superharness/models.yaml` overrides with deep merge at agent level
- [ ] Partial overrides work (only `claude-code.mini` → rest preserved)
- [ ] All existing `model_router` and `sdk_runner` tests still pass
- [ ] 12+ new tests pass in `test_model_config.py`

#### Watch out for
- **Previous attempt timed out at 268K tokens** — the task is medium complexity. Stay focused: don't over-engineer, don't add tests beyond the 12 listed above.
- Use `importlib.resources` (not `__file__`) to locate bundled YAML — same pattern as `watcher_worker.py`
- The cache must be invalidated in tests using `monkeypatch` or by directly resetting the module-level `_cached_map = None`

---

### TASK 2 — `harden.R5-scaling-docs` (priority: low, do after R3)
**Document scaling limits in spec and architecture docs**

#### What to Write

**`protocol/spec.md`** — add a "## Scaling & Limits" section:

| Component | Recommended Limit | Why |
|-----------|-------------------|-----|
| Tasks per contract | < 200 | O(n) per query in `validate.py` |
| Active inbox items | < 100 | O(n) per dispatch cycle |
| Ledger lines | < 10,000 | O(n) per `grep` in `recall` |
| Handoff files | < 500 | O(n) per glob in `hygiene` |

Include recommendation: archive done tasks after 100+ accumulate (move to `contract-archive.yaml`).

**`docs/ARCHITECTURE.md`** — add a "## Performance Characteristics" subsection under the relevant section with the same table and a note about the watcher poll interval tradeoff (shorter = more responsive, more CPU).

**`README.md`** — add a one-liner: `> For projects with >200 tasks or >10,000 ledger lines, see [Scaling & Limits](protocol/spec.md#scaling--limits).`

#### TDD for R5
Write 5 content-presence tests in `tests/unit/test_scaling_docs.py`:
1. `test_spec_has_scaling_section` — `spec.md` contains `## Scaling` heading
2. `test_spec_has_limits_table` — `spec.md` contains `< 200` (task limit)
3. `test_architecture_has_performance_section` — `ARCHITECTURE.md` contains `Performance`
4. `test_architecture_has_limits_table` — `ARCHITECTURE.md` contains `< 10,000`
5. `test_readme_links_scaling` — `README.md` contains `Scaling`

---

## Inbox State

Both tasks are **paused** in the inbox. To resume them:

```python
import yaml
path = '/Users/airm2max/DevOpsSec/superharness/.superharness/inbox.yaml'
with open(path) as f:
    inbox = yaml.safe_load(f)
items = inbox if isinstance(inbox, list) else inbox.get('items', [])
for i in items:
    if i.get('status') == 'paused':
        i['status'] = 'pending'
        print('resumed:', i.get('task'))
with open(path, 'w') as f:
    yaml.dump(inbox, f, default_flow_style=False)
```

Or just run each task directly without the inbox — read the contract, implement, run tests, write handoff.

---

## How to Write Your Handoff When Done

For each task, write to `.superharness/handoffs/harden.RX-<task>-2026-03-27-codex-cli.yaml`:

```yaml
task: harden.R3-models
phase: report
status: report_ready
from: codex-cli
to: owner
date: <ISO timestamp>
outcome: |
  <what you did>
context: |
  <what next session needs to know>
outcomes:
  - <bullet>
tests_passed: true
```

Then update `.superharness/contract.yaml` task status to `report_ready`.

---

## Run Tests Before Handoff

```bash
cd /Users/airm2max/DevOpsSec/superharness
pytest tests/unit/test_model_config.py -v          # new R3 tests
pytest tests/unit/test_scaling_docs.py -v          # new R5 tests
pytest tests/ -q                                    # full suite — must all pass
```

**Target: ~1,012+ tests passing after both tasks.**
