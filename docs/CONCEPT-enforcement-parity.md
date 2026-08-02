# CONCEPT — crossprose test patterns ported to superharness (enforcement parity)

Target repo: `~/DevOpsSec/superharness` (branch off `origin/main`)
Source design docs: pattern source is `~/DevOpsSec/crossprose/tests/unit/test_ci_parity.py`; motivating incident is `docs/bugs/BUG-2026-07-31-test-suite-git-dir-escape.md` (in superharness).

## 1. Scope summary

Port three test patterns from crossprose that pin "enforcement surfaces that silently don't enforce": (1) `--strict-markers` so a typo'd pytest marker fails collection instead of silently passing; (2) CI-parity contract tests that read `.github/workflows/tests.yml`, `.project-hooks/pre-commit`, and `pyproject.toml` as data and assert their enforcement commands stay intact — including byte-equality of the duplicated hook directories; (3) a completeness sweep asserting every adapter hook has a corresponding test file, with a ratchet allowlist for currently-untested hooks so the gap can shrink but never grow.

NOT being built: any change to the hooks themselves, any CI workflow change, closing the ratchet allowlist (writing tests for currently-untested hooks is follow-up work), and any crossprose-style declarative workflow adoption (separate design decision).

Smallest possible v1: Iteration 1 alone (`--strict-markers`, one line plus verification).

## 2. Prerequisites

Dependencies:
- Existing superharness dev environment (`.venv`, pytest 9). `pyyaml` is already a runtime dependency (`pyproject.toml` line 25), needed to parse workflow YAML in Iteration 2.
- No new packages.

Existing code areas touched:
- `pyproject.toml` — `[tool.pytest.ini_options]` block (currently has `testpaths`, `pythonpath`, `markers`; no `addopts`).
- `tests/contract/` — the repo's established home for config-as-data enforcement tests (`test_source_ratchets.py` is the in-repo precedent for the ratchet pattern; read it before Iteration 3).
- Read-only as data: `.github/workflows/tests.yml`, `.project-hooks/pre-commit`, `adapters/claude-code/hooks/`, `src/superharness/adapters/claude-code/hooks/`.

Risks:
- `--strict-markers` fails collection if any unregistered marker exists. Measured on 2026-08-01: the only `pytest.mark.*` uses across `tests/` are builtins (`skip` 336, `parametrize` 85, `skipif` 46, `xfail` 3) plus registered `regression` (6). Risk is a marker applied via a module-level `pytestmark` variable the grep missed — Iteration 1's full collection run catches that deterministically.
- The completeness sweep's initial allowlist must reflect reality at implementation time; the executor derives it from the actual failure output, not from this plan.

Side-effect fence (all iterations): repo tree only, in a worktree branched from `origin/main`. Tests read workflow/hook files as data — they must never execute hooks against the real repo, spawn agents, or touch `.superharness` state. The `_real_repo_untouched` autouse guard (merged in PR #88) is active and will fail any violation. Do not run the full pre-commit suite from inside a git hook context; committing normally is safe (hook runs the fast subset, ~19s).

## 3. Iterations

#### Iteration 1 — `--strict-markers`

**Goal:** Unknown pytest markers become collection errors instead of silently-passing decoration.

**Shippable on its own?** Yes — one config line plus a pinning test.

**Source references:**
- pyproject.toml — current `[tool.pytest.ini_options]` block (lines 67-74 on main: `testpaths`, `pythonpath`, `markers` with `requires_bash`, `regression`, `network`). Verify the exact block before editing; `addopts` does not exist yet and must be added, not appended to.

Pattern note (executor): the form comes from crossprose's pyproject (`addopts = "-ra --strict-markers"`) at `~/DevOpsSec/crossprose/pyproject.toml` — read for form only; it is outside this repo.

**Files touched:**
- pyproject.toml (modified)
- tests/contract/test_pytest_config.py (new)

**Commit message:**
`chore(tests): enable --strict-markers so a typo'd marker fails collection`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/contract/test_pytest_config.py::test_addopts_enables_strict_markers` — parses `pyproject.toml` (`tomllib`), asserts `"--strict-markers"` is in `tool.pytest.ini_options.addopts`. Fails before the config edit.
  - `tests/contract/test_pytest_config.py::test_all_declared_markers_have_descriptions` — every entry in `markers` contains a `:` followed by non-empty text (a bare name silently registers nothing useful).
- GREEN (minimal implementation to pass RED):
  - Add `addopts = "-ra --strict-markers"` to `[tool.pytest.ini_options]`. `-ra` included deliberately: prints the skip/xfail summary, which this suite (531+ skips) currently hides.
  - Then run full collection (`pytest --collect-only -q`) — if any unregistered marker surfaces (e.g. via a `pytestmark` module variable), register it in `markers` with a description rather than removing the flag.
- REFACTOR (cleanup planned after GREEN):
  - None.

**Test pyramid for this iteration:**
- Smoke: `pytest --collect-only -q` exits 0 with the flag active (collection is the surface this changes).
- Unit: the 2 RED tests are the unit level here — each isolates one config fact (`addopts` contents; marker descriptions) with no cross-component surface.
- Integration: N/A.
- State machine: N/A.
- Contract: same 2 tests double as the contract layer (repo config as data).
- Regression: none fixed here — pure hardening. Named risk: collection breakage from a hidden unregistered marker; caught by the smoke step, resolved by registering.
- Chaos: N/A.
- E2E: N/A.
- Performance: N/A.
- TDD Parity: 100% — no new public symbols; both behaviors pinned by the contract tests.
- Coverage: +0% → 56% (test-only change; `fail_under = 56` untouched).

**Acceptance criteria (binary):**
- [ ] `.venv/bin/pytest tests/ --collect-only -q` exits 0.
- [ ] A scratch test file using `@pytest.mark.netwrok` (typo) fails collection with "not a registered marker" when run with the repo config, and is deleted after demonstration.
- [ ] Both contract tests pass.

**Estimated effort:** S

**Blocked by:** None

#### Iteration 2 — CI-parity contract tests

**Goal:** The enforcement commands in CI, the pre-commit hook, and the duplicated hook directories are pinned by tests that read them as data, so silent de-fanging (the branch-guard disease) cannot recur unnoticed.

**Shippable on its own?** Yes — pure test addition.

**Source references:**

Pattern note (executor): the form comes from `~/DevOpsSec/crossprose/tests/unit/test_ci_parity.py` — `yaml.safe_load` the workflow, join step `run:` strings, assert substrings. Read for form only; it is outside this repo, do not copy paths.
- .github/workflows/tests.yml — lines 104-120 on main hold the unit-job run commands (`python3 -m pytest tests/unit -q ... --cov=superharness --cov-fail-under=56`, one variant with `--timeout=120`, a Windows variant without). Verify exact job names/keys at implementation time; the plan pins substrings, not full commands.
- .project-hooks/pre-commit — on main after PR #83/#81 it must contain the `unset GIT_DIR ...` line, `-m "not network"`, the four subset paths (`tests/smoke tests/contract tests/state_machine tests/unit/test_git_env_isolation.py`), and the `SUPERHARNESS_FULL_PRECOMMIT` escape hatch. Read the current file before writing assertions.
- adapters/claude-code/hooks/ and src/superharness/adapters/claude-code/hooks/ — the two copies that PR #87's commit message says "must stay byte-identical"; that sentence is the unenforced contract this iteration enforces.

**Files touched:**
- tests/contract/test_enforcement_parity.py (new)

**Commit message:**
`test(contract): pin CI, pre-commit hook, and hook-copy enforcement surfaces`

**TDD cycle:**
- RED (failing tests to write first — they pass immediately against a correct repo, so RED is demonstrated by mutation: temporarily break each surface in the worktree, observe the failure message, revert; the executor performs this check for each test and notes it in the commit body):
  - `tests/contract/test_enforcement_parity.py::test_precommit_unsets_git_plumbing_env` — hook text contains `unset GIT_DIR` and `GIT_INDEX_FILE` (the 2026-07-31 escape vector; see bug report).
  - `tests/contract/test_enforcement_parity.py::test_precommit_deselects_network_tests` — hook text contains `-m "not network"` in both branches (fast subset and `SUPERHARNESS_FULL_PRECOMMIT=1`).
  - `tests/contract/test_enforcement_parity.py::test_precommit_subset_includes_git_env_guard` — hook text contains `tests/unit/test_git_env_isolation.py`; that file exists.
  - `tests/contract/test_enforcement_parity.py::test_ci_unit_job_runs_full_unit_suite` — parsed `tests.yml` unit-job run text contains `pytest tests/unit` (CI must not inherit the hook's subset).
  - `tests/contract/test_enforcement_parity.py::test_ci_coverage_floor_matches_pyproject` — the `--cov-fail-under=` value in the unit-job run text equals `tool.coverage.report.fail_under` in `pyproject.toml` (currently both 56; pinning the *equality*, not the number).
  - `tests/contract/test_enforcement_parity.py::test_hook_copies_are_byte_identical` — for every file in `src/superharness/adapters/claude-code/hooks/`, an identically-named file exists in `adapters/claude-code/hooks/` with identical bytes, and vice versa (both directions, so a file added to one side alone also fails).
  - `tests/contract/test_enforcement_parity.py::test_subset_paths_exist` — every `tests/...` path named in the hook exists on disk (a renamed directory would otherwise turn the hook into a no-op that exits 0).
- GREEN (minimal implementation to pass RED):
  - Module-level helpers: `_repo_root()` (three `parents` up from the test file), `_hook_text()`, `_ci_unit_run_text()` using `yaml.safe_load`; each test is 3-6 lines of substring/equality assertions with failure messages that quote the offending text.
- REFACTOR (cleanup planned after GREEN):
  - None expected.

**Test pyramid for this iteration:**
- Smoke: the new file imports and collects under `--strict-markers` (Iteration 1 landed).
- Unit: the two private helpers (`_hook_text`, `_ci_unit_run_text`) are exercised by every one of the 7 tests; each test isolates exactly one enforcement fact, which is this iteration's unit granularity.
- Integration: N/A — files read as data, nothing executed.
- State machine: N/A.
- Contract: all 7 tests above — this whole iteration is the contract layer.
- Regression: `test_precommit_unsets_git_plumbing_env` and `test_hook_copies_are_byte_identical` are regression pins for the 2026-07-31 incident and PR #87's prose-only invariant respectively.
- Chaos: mutation check in RED (break surface → observe failure → revert) is the fault-injection step, performed once per test during implementation.
- E2E: N/A.
- Performance: N/A.
- TDD Parity: 100% — helpers are private; every assertion surface has a test by construction.
- Coverage: +0% → 56% (tests only).

**Acceptance criteria (binary):**
- [ ] All 7 tests pass on an unmodified worktree of `origin/main`.
- [ ] Deleting the `unset GIT_DIR` line from the hook in a scratch copy makes `test_precommit_unsets_git_plumbing_env` fail with a message naming the hook path (mutation check, then reverted).
- [ ] Changing one byte in one hook copy makes `test_hook_copies_are_byte_identical` fail naming the file (mutation check, then reverted).

**Estimated effort:** S

**Blocked by:** Iteration 1

#### Iteration 3 — hook-test completeness ratchet

**Goal:** Every hook shipped in `adapters/claude-code/hooks/` maps to a test file; hooks without one live in an explicit shrinking allowlist, so a new untested guard cannot land silently.

**Shippable on its own?** Yes.

**Source references:**
- tests/contract/test_source_ratchets.py — the repo's existing ratchet precedent; read it and match its allowlist/failure-message style so the two ratchets feel like one convention.

Pattern note (executor): the completeness-sweep form comes from `~/DevOpsSec/crossprose/tests/unit/test_recipes_complete.py` — outside this repo, read for form only.
- adapters/claude-code/hooks/ — current inventory on main: `branch-guard.sh`, `branch_guard.py`, `hooks.json`, `ledger-append.sh`, `scope-guard.sh`, `session-exit.sh`, `session-start.sh`, `session-stop.sh`, `session-turn-end.sh`. Verify at implementation time; PR #87 added `branch_guard.py` recently.

**Files touched:**
- tests/contract/test_hook_test_coverage.py (new)

**Commit message:**
`test(contract): ratchet — every adapter hook needs a test file or an allowlist entry`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/contract/test_hook_test_coverage.py::test_every_hook_has_a_test_or_allowlist_entry` — for each `*.sh`/`*.py` hook in `adapters/claude-code/hooks/`, derive candidate test names (`test_<stem underscored>.py`, e.g. `branch-guard.sh` → `tests/unit/test_branch_guard.py`) and assert the file exists OR the hook is in `KNOWN_UNTESTED`. Written with `KNOWN_UNTESTED = []` first so it fails and prints the true gap list; the executor then moves the actual failures into the allowlist with one comment line each explaining what a future test should cover. Expected gap set (verify against the failure output, do not trust this plan): `ledger-append.sh`, `session-exit.sh`, `session-start.sh`, `session-turn-end.sh`. `hooks.json` is config, not executable — excluded by pattern.
  - `tests/contract/test_hook_test_coverage.py::test_allowlist_entries_are_still_untested` — every `KNOWN_UNTESTED` entry still lacks a test file; when someone writes the test, this fails and forces the allowlist to shrink (the ratchet's other jaw — prevents stale entries).
  - `tests/contract/test_hook_test_coverage.py::test_allowlist_names_real_hooks` — every allowlist entry exists in the hooks directory (a deleted hook cannot haunt the list).
- GREEN (minimal implementation to pass RED):
  - One module: `HOOKS_DIR`, `KNOWN_UNTESTED` with per-entry comments, a `_candidate_test_paths(hook_name)` helper, three tests. Failure message instructs: "write tests/unit/test_<name>.py or add to KNOWN_UNTESTED with a justification comment — see docs/bugs/BUG-2026-07-31-test-suite-git-dir-escape.md for why untested guards are the most dangerous kind."
- REFACTOR (cleanup planned after GREEN):
  - None.

**Test pyramid for this iteration:**
- Smoke: file collects and runs under `--strict-markers`.
- Unit: `_candidate_test_paths` covered implicitly by the three tests; no other logic.
- Integration: N/A.
- State machine: N/A.
- Contract: all 3 tests — directory structure as contract.
- Regression: pins the session meta-lesson (branch-guard drifted unnoticed because guard code had thin tests); an allowlisted hook is at least *visibly* untested.
- Chaos: mutation check — add a fake `new-guard.sh` to the hooks dir in the worktree, observe the ratchet fail naming it, remove it.
- E2E: N/A.
- Performance: N/A.
- TDD Parity: 100%.
- Coverage: +0% → 56%.

**Acceptance criteria (binary):**
- [ ] All 3 tests pass on `origin/main` with the derived allowlist.
- [ ] Adding a fake hook file in a scratch copy fails the sweep naming it (mutation check, then reverted).
- [ ] Every `KNOWN_UNTESTED` entry carries a one-line comment saying what a future test should cover.

**Estimated effort:** S

**Blocked by:** Iteration 2

## 4. Test inventory summary

| Iter | Smoke | Unit | Integration | State machine | Contract | Regression | Chaos | E2E | Performance | TDD Parity | Coverage Δ |
|------|-------|------|-------------|---------------|----------|------------|-------|-----|-------------|------------|------------|
| 1    | 1     | 0    | 0           | 0             | 2        | 0          | 0     | 0   | 0           | 100%       | +0% → 56%  |
| 2    | 1     | 0    | 0           | 0             | 7        | 2          | 1     | 0   | 0           | 100%       | +0% → 56%  |
| 3    | 1     | 0    | 0           | 0             | 3        | 1          | 1     | 0   | 0           | 100%       | +0% → 56%  |

Unit rows are legitimately 0: every test in this plan is a contract test over repo files as data; there are no new functions to unit-test.

## 5. End-to-end definition of done

Deduplicated acceptance criteria:
- Full collection passes with `--strict-markers`; a deliberately typo'd marker fails collection (demonstrated, then removed).
- All 12 new contract tests pass on unmodified `origin/main`.
- Each enforcement pin was mutation-checked once: surface broken → named failure → reverted.
- Ratchet allowlist derived from actual failure output, each entry commented; adding a fake hook fails the sweep.
- No hook, workflow, or source file modified — `pyproject.toml` and three new test files are the entire diff (plus CHANGELOG lines; union driver from PR #87 handles parallel-branch appends).

Manual demo (operator-run):
```bash
cd ~/DevOpsSec/superharness && .venv/bin/pytest tests/contract/test_pytest_config.py tests/contract/test_enforcement_parity.py tests/contract/test_hook_test_coverage.py -q
```
Then break something on purpose — delete the `unset GIT_DIR` line from `.project-hooks/pre-commit` — rerun, watch `test_precommit_unsets_git_plumbing_env` fail with the hook path in the message, restore the line.

Green command at the end:
```bash
cd ~/DevOpsSec/superharness && PYTHONPATH=. .venv/bin/pytest tests/contract/test_pytest_config.py tests/contract/test_enforcement_parity.py tests/contract/test_hook_test_coverage.py tests/contract/test_manifest_compliance.py tests/contract/test_source_ratchets.py -q
```
(The two existing contract files are included to prove the new addopts didn't disturb them.)

## 6. Out of scope

- Writing tests for the allowlisted hooks (`ledger-append.sh`, `session-*.sh`) — separate follow-up per hook; the ratchet makes the gap visible, which is this plan's job.
- Any CI workflow edit (e.g. adding `pytest-xdist -n auto --dist loadfile`) — separate decision with its own PR; one green parallel run is not a track record.
- Raising `fail_under` above 56 or enabling branch coverage — measure after coverage gains land, not before.
- crossprose declarative-spec adoption for `shux develop` — open architecture decision, owner's call.
- Extending parity pins to `ci-matrix.yml` / `security.yml` / `shell-guard.yml` — start with the workflow that gates merges; extend later if drift appears.

## 7. Open questions

None.
