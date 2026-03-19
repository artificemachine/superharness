# superharness Improvement Plan

*v0.8.0 → 1.0 — Based on repo analysis + Anthropic "Effective Harnesses for Long-Running Agents" (Nov 2025)*

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Done |
| 🔴 | High priority |
| 🟡 | Medium priority |
| 🟢 | Lower priority |

---

## ✅ shux monitor — Auto Project + Browser Open

**Shipped:** 2026-03-15

- `scripts/monitor-ui.py` — `--project` optional (defaults to cwd), `--no-open` flag, auto-opens browser
- `src/superharness/cli.py` — auto-injects `--project <cwd>` when not supplied

```bash
shux monitor           # detects cwd, starts server, opens browser
shux monitor --no-open # starts server, prints URL only
```

---

## ✅ shux test-type — Mandatory Test Types on Tasks

**Shipped:** 2026-03-15

- New `src/superharness/commands/test_type.py` — attaches `test_types: [...]` to a contract task
- Interactive numbered menu when called bare (unit, integration, e2e, manual, smoke)
- Non-interactive flags: `--set`, `--add`, `--remove`, `--show`
- `shux hygiene` warns on `done` tasks with `test_types` but no verified evidence

```bash
shux test-type --id feat-001                    # interactive prompt
shux test-type --id feat-001 --set unit --set e2e
shux test-type --id feat-001 --add smoke
shux test-type --id feat-001 --show
```

---

## ✅ Iteration 1 — Distribution & Trust

**Shipped:** 2026-03-19

**Goal:** `pipx install superharness` becomes the canonical install path.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter1.pypi.verify-pyproject` | Verify pyproject.toml is PyPI-ready | ✅ done |
| `iter1.pypi.testpypi` | Build and publish to TestPyPI | ✅ done (publish.yml handles both) |
| `iter1.pypi.github-actions` | Add GitHub Actions publish.yml (OIDC, auto-release) | ✅ done |
| `iter1.pypi.update-readme` | Update README: pipx first, curl fallback + SHA256 checksum | ✅ done |

**Evidence:**
- `pyproject.toml`: name, version, description, readme, license, requires-python, dependencies, entry_points all correct
- `.github/workflows/publish.yml`: OIDC Trusted Publishing, triggers on release
- README leads with `pipx install superharness`, curl fallback in `<details>` dropdown
- `build` and `twine` available locally for manual publishing

---

## ✅ Iteration 2 — Protocol Enforcement: `shux verify`

**Shipped:** 2026-03-19

**Goal:** Block `shux close` unless a verification record exists.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter2.verify.design` | Design verify command schema and ledger format | ✅ done |
| `iter2.verify.implement` | Implement shux verify command in CLI | ✅ done |
| `iter2.verify.gate` | Gate shux close on verified: true | ✅ done |
| `iter2.verify.hygiene` | Add verify coverage check to shux hygiene | ✅ done |
| `iter2.verify.agents-md` | Add Verification Policy section to AGENTS.md | ✅ done |

**Evidence:**
- `src/superharness/commands/verify.py`: `--id`, `--method`, `--result pass|fail`, `--actor`
- Sets `verified: true/false`, `verified_at`, `verified_by` on contract task
- Appends `VERIFY PASS|FAIL` entry to ledger.md
- `close.py` blocks if `verified: true` not set (bypass: `--skip-verify`)
- `validate.py` warns on done tasks without verification record
- AGENTS.md has Verification Policy section
- 15 tests in `test_verify_and_close.py`

---

## ✅ Iteration 3 — Feature Tracking at Init Time

**Shipped:** 2026-03-19

**Goal:** Generate `features.json` at `shux init` so agents have a global definition of done.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter3.features.schema` | Define features.json schema and validation rules | ✅ done |
| `iter3.features.init-prompt` | Add features.json generation to shux init flow | ✅ done |
| `iter3.features.enforce` | Enforce append-only rule in shux hygiene | ✅ done |

**Evidence:**
- `protocol/features.schema.json`: id, category, description, steps[], passes (bool)
- `init_project.py` `_generate_features()`: stack-aware generation (Python, Docker, etc.)
- `validate.py`: hygiene checks for features.json structure, duplicates, missing fields
- 8 tests in `test_features.py`

---

## ✅ Iteration 4 — Platform Parity: Linux systemd

**Shipped:** 2026-03-19

**Goal:** Match the macOS launchd installer with a Linux counterpart.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter4.systemd.installer` | Write install-systemd-watcher.sh | ✅ done |
| `iter4.systemd.readme` | Update README watcher section for macOS + Linux | ✅ done |

**Evidence:**
- `src/superharness/scripts/install-systemd-inbox-watcher.sh`: 235 lines, full arg parsing,
  confirmation gate, unit+timer generation, daemon-reload+enable+start
- README Platform Support section covers both macOS and Linux
- `docs/UNATTENDED.md` has full systemd setup walkthrough
- `doctor.py` handles Linux platform with appropriate messaging

---

## ✅ Iteration 5 — Documentation

**Shipped:** 2026-03-19

**Goal:** Surface the two most unique features with worked examples.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter5.docs.discuss` | Write docs/DISCUSS.md with full worked example | ✅ done |
| `iter5.docs.unattended` | Write docs/UNATTENDED.md with overnight run walkthrough | ✅ done |

**Evidence:**
- `docs/DISCUSS.md`: 146 lines — two-agent disagreement, discussion rounds, resolution, decisions.yaml
- `docs/UNATTENDED.md`: 141 lines — launchd + systemd setup, ledger next morning, failure handling

---

## ✅ Iteration 6 — Visibility

**Shipped:** 2026-03-19

**Goal:** Drive discovery with a comparison post contrasting superharness with Anthropic's approach.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter6.blog.draft` | Draft comparison blog post → docs/blog-comparison-draft.md | ✅ done |

**Evidence:**
- `docs/blog-comparison-draft.md`: 109 lines — comparison table, what Anthropic got right,
  what superharness adds, who should use what, try-it CTA

---

## Verification Checklist (per iteration)

| Check | Command | Status |
|-------|---------|--------|
| Protocol compliance | `shux hygiene` | ✅ |
| Tests green | `pytest` (727 passing) | ✅ |
| iter1: install works | `pipx install superharness` from PyPI | ⏳ pending first release |
| iter2: gate active | `shux close <unverified-id>` must fail with actionable error | ✅ |
| iter3: init generates features | `shux init` in fresh dir → `.superharness/features.json` with all `passes: false` | ✅ |
| iter4: systemd install | `bash scripts/install-systemd-watcher.sh` on Linux | ✅ (script complete, needs Linux test) |

---

## 1.0 Release Criteria

All improvement plan iterations are complete. Remaining before 1.0:

1. **Publish to PyPI** — Create a GitHub Release to trigger `publish.yml` (OIDC auto-publish)
2. **Verify `pipx install superharness`** works end-to-end from PyPI
3. **Tag v1.0.0** after PyPI verification
