# BUG 2026-07-31 — test suite escapes onto the real repo when run from a git hook (`GIT_DIR` overrides `cwd`)

**Severity:** high — corrupts the working repo's `.git/config`, writes junk commits and stashes into real history, and silently disables the pre-commit security hooks.
**Status:** open. Damage from the 2026-07-31 18:26 occurrence has been repaired by hand; the defect itself is unfixed.

## Summary

`.project-hooks/pre-commit` runs the entire pytest suite:

```bash
#!/bin/bash
set -euo pipefail

PYTHONPATH=. .venv/bin/pytest tests -q
```

Git sets `GIT_DIR` (and often `GIT_INDEX_FILE`) in the environment of every hook it invokes. **`GIT_DIR` takes precedence over both `cwd=` and `git -C`.** So when the suite runs from inside the hook, every test that shells out to git — even one correctly scoped to `tmp_path` — operates on the *real* repository instead.

Net effect: running `git commit` in this repo can corrupt this repo.

## Reproduction (verified 2026-07-31)

```bash
git init -q /tmp/realrepo
git -C /tmp/realrepo config user.email real@real.com
mkdir -p /tmp/fake

git -C /tmp/realrepo config --get user.email
# real@real.com

# a correctly-scoped test-style call, but with GIT_DIR set the way a hook sets it
GIT_DIR=/tmp/realrepo/.git git -C /tmp/fake config user.email leak@leak.com

git -C /tmp/realrepo config --get user.email
# leak@leak.com        <-- wrote to the real repo despite -C /tmp/fake
```

`git init` behaves the same way: with `GIT_DIR` set it reports `Reinitialized existing Git repository in /tmp/realrepo/.git/` and ignores the target path entirely.

## Observed damage (2026-07-31, `pytest-413` session, 18:21:32–18:26:54)

`~/Library/Logs/superharness/superharness-audit.log` shows the run spanning that window. `~/DevOpsSec/superharness/.git/config` was rewritten at 18:26:48, inside it.

| Setting | Left as | Correct |
|---|---|---|
| `core.bare` | `true` | `false` |
| `core.hooksPath` | `/dev/null` | unset (inherit `~/.githooks`) |
| `user.email` | `test@test.com` | `newblacc@users.noreply.github.com` |
| `user.name` | `Test` | `newblacc` |

`core.bare = true` made `git status` fail repo-wide with `fatal: this operation must be run in a work tree`. `core.hooksPath = /dev/null` disabled the global pre-commit protections (secret scan, ShipGuard SAST, hardcoded-path check, CHANGELOG guard) for as long as it stood.

Also written into real history: commits `621c72d7 "init"` and `14b36aed "i"` (a disjoint history containing only `test.txt`), plus stash `On docs/pi-develop-plan: shux-checkpoint:test-task`.

## Attribution to specific tests

- `tests/unit/test_checkpoint.py:14` — `git commit --no-verify -m "i"` produces the junk commit message `i` exactly.
- `tests/unit/test_checkpoint.py:10` — writes `test.txt`, the only file in the junk commits.
- `tests/unit/test_checkpoint.py:21` — `snapshot(str(tmp_path), "test-task")` produces `shux-checkpoint:test-task`, matching the junk stash tag exactly, via `src/superharness/guard/checkpoint.py:12`.
- `tests/unit/test_module_ship.py:21,27,34` — writes `user.email`, `user.name`, and `core.hooksPath /dev/null`, matching three of the four damaged settings.

Every one of these call sites is *correctly written* (`cwd=tmp_path` or `git -C`). They are not the defect. The defect is that the suite is invoked in an environment where that scoping does not hold.

**Unresolved:** the origin of `core.bare = true` specifically. Reproduction attempts with `GIT_DIR` set plus `cwd` outside the worktree did not flip `core.bare`. Do not treat that one as explained.

## Contributing factors

1. `tests/conftest.py` scrubs `SUPERHARNESS_STATE_DIR` / `XDG_STATE_HOME` (autouse `isolated_state_dir`, with a `_state_dir_guardrail` that fails any test whose DB escapes tmp) but does **not** scrub `GIT_DIR`, `GIT_WORK_TREE`, or `GIT_INDEX_FILE`. The state-dir escape is guarded; the git escape is not.
2. `src/superharness/modules/actions/ship.py:22` — `project_dir = Path(context.get("project_dir", "."))`. A caller omitting `project_dir` silently targets the process CWD. Not implicated in this incident (all three test call sites pass it), but it is the same class of defect.
3. `~/.local/state/superharness/` holds 2126 state directories, suggesting test-state leakage has been accumulating for a long time.

## Suggested fixes, cheapest first

1. **Scrub the git env in an autouse conftest fixture** — `monkeypatch.delenv` on `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_COMMON_DIR` for every test. One fixture, mirrors the existing `isolated_state_dir` pattern, fixes the whole class.
2. **Add a guardrail assertion** alongside `_state_dir_guardrail` that fails any test whose git writes land outside `tmp_path`, so a regression is loud instead of silent.
3. **Stop running the full suite from the pre-commit hook.** A hook that can corrupt the repo it guards is a bad trade. Run a fast subset there, or move the suite to CI. At minimum have `.project-hooks/pre-commit` `unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE` before invoking pytest.
4. **Remove the `"."` default** at `ship.py:22` — require `project_dir` and fail loudly when it is missing.

## Why this blocks `shux develop`

`docs/CONCEPT-develop-until-approved.md` proposes an orchestration engine that creates git worktrees, commits inside them, and merges branches back — all through the same subprocess-git layer, and its own tests would exercise exactly that. The identical escape there would not stop at config drift; it would merge agent branches into the real repo. Fix this before implementing Iteration 3.
