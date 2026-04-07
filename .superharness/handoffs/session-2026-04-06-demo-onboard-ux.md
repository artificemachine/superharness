# Session Handoff — 2026-04-06T19:52Z

**From:** claude-code  
**To:** owner / next session  
**Branch:** merged to `main` as of this session  
**Version:** 1.11.1 (shipped to PyPI)

---

## What Was Done

### 1. UX intro for `shux demo` and `shux onboard`
Both commands now open with a "what is superharness" block before doing anything:
- Explains the problem (agents forgetting context)
- Lists the 3 key files (`contract.yaml`, `handoffs/`, `inbox.yaml`)
- Shows the task flow
- Lists the 5 core commands

### 2. Step marker ordering fix in `shux demo`
Step markers (`── N / 5`) were printing after subprocess output when stdout was piped.
Fixed by calling `sys.stdout.flush()` inside the `step()` helper before subprocess calls.

### 3. Adapter hooks bundled in the package
`adapters/claude-code/hooks/` copied into `src/superharness/adapters/` and added to
`pyproject.toml` package-data. `_find_hooks_dir()` in `install_hooks.py` now checks
the in-package location first, then falls back to the editable install path.

This fixes the `error: Adapter hooks directory not found` that appeared in `shux demo`
and `shux onboard` after a `pip install` or `pipx install` without a repo checkout.

### 4. Shell entrypoint allowlist updated
`src/superharness/scripts/check-shell-entrypoints.sh` — added 6 new entries for
the `src/superharness/adapters/claude-code/` scripts.

### 5. Docs
- `docs/GUIDE.md`: added `shux demo` to command table; new section "Exploring
  superharness (`shux demo`)" covering the walkthrough and adapter bundling fix.
- `shux onboard` section updated to mention the intro block.

### 6. Stale task closed
`feat.always-on-dispatch` was in `todo` state despite being merged in `cb1ae49`.
Advanced to `report_ready` and closed.

---

## Files Changed

| File | Change |
|------|--------|
| `src/superharness/commands/demo.py` | Added intro block + stdout flush fix |
| `src/superharness/commands/onboard.py` | Added intro block |
| `src/superharness/commands/install_hooks.py` | Two-path `_find_hooks_dir()` |
| `src/superharness/adapters/` | New — adapter hooks bundled in package |
| `src/superharness/scripts/check-shell-entrypoints.sh` | Allowlist +6 entries |
| `pyproject.toml` | Package-data + version bump 1.11.0 → 1.11.1 |
| `docs/GUIDE.md` | `shux demo` entry + section |
| `CHANGELOG.md` | 1.11.1 entry appended |

---

## Ship Summary

- PR #88 merged (squash) to `main`
- Tag `v1.11.1` auto-created by release workflow
- GitHub release: https://github.com/celstnblacc/superharness/releases/tag/v1.11.1
- Published to PyPI: `pipx install superharness==1.11.1`

---

## Known / Open Items

- `security.yml` pins `shipguard==0.3.2` but latest is `0.3.3` — minor, not blocking.
- Node.js 20 deprecation warnings in all GitHub Actions workflows — update action
  SHA pins to Node.js 24-compatible versions before June 2026.
- `shipguard.txt` in repo root is a generated scan artifact — consider adding it
  to `.gitignore` to avoid accidental commits.

---

## Next Session Starting Point

```
shux contract     # verify clean state
shux doctor       # health check
shux demo         # verify the new UX intro end-to-end
```
