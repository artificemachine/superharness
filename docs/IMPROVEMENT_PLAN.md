# superharness Improvement Plan

*v0.8.0 → next — Based on repo analysis + Anthropic "Effective Harnesses for Long-Running Agents" (Nov 2025)*

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

## Iteration 1 — Distribution & Trust 🔴

**Goal:** `pipx install superharness` becomes the canonical install path.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter1.pypi.verify-pyproject` | Verify pyproject.toml is PyPI-ready | todo |
| `iter1.pypi.testpypi` | Build and publish to TestPyPI | todo |
| `iter1.pypi.github-actions` | Add GitHub Actions publish.yml (OIDC, auto-release) | todo |
| `iter1.pypi.update-readme` | Update README: pipx first, curl fallback + SHA256 checksum | todo |

### shux task commands

```bash
superharness task create -p . \
  --id iter1.pypi.verify-pyproject \
  --title "Verify pyproject.toml is PyPI-ready" \
  --owner claude-code \
  --criteria "name, version, description, readme, license, requires-python all present" \
  --criteria "entry_points resolve to actual module:function" \
  --criteria "dependencies list is complete (pyyaml, click, ruamel.yaml)"

superharness task create -p . \
  --id iter1.pypi.testpypi \
  --title "Build and publish to TestPyPI" \
  --owner claude-code \
  --dependency iter1.pypi.verify-pyproject \
  --criteria "python -m build produces .tar.gz and .whl in dist/" \
  --criteria "twine upload --repository testpypi succeeds" \
  --criteria "pipx install from TestPyPI works and shux --version returns correct version"

superharness task create -p . \
  --id iter1.pypi.github-actions \
  --title "Add GitHub Actions publish.yml for auto-release to PyPI" \
  --owner claude-code \
  --dependency iter1.pypi.testpypi \
  --criteria ".github/workflows/publish.yml exists" \
  --criteria "Triggers on release: [published]" \
  --criteria "Uses PyPI Trusted Publishing (OIDC, no API token)" \
  --criteria "Workflow linted and passes yamllint"

superharness task create -p . \
  --id iter1.pypi.update-readme \
  --title "Update README install section to lead with pipx" \
  --owner claude-code \
  --dependency iter1.pypi.github-actions \
  --criteria "README shows pipx install superharness as primary install" \
  --criteria "curl one-liner moved to secondary/fallback" \
  --criteria "SHA256 checksum published alongside curl one-liner"
```

---

## Iteration 2 — Protocol Enforcement: `shux verify` 🔴

**Goal:** Block `shux close` unless a verification record exists.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter2.verify.design` | Design verify command schema and ledger format | todo |
| `iter2.verify.implement` | Implement shux verify command in CLI | todo |
| `iter2.verify.gate` | Gate shux close on verified: true | todo |
| `iter2.verify.hygiene` | Add verify coverage check to shux hygiene | todo |
| `iter2.verify.agents-md` | Add Verification Policy section to AGENTS.md | todo |

### shux task commands

```bash
superharness task create -p . \
  --id iter2.verify.design \
  --title "Design shux verify command schema and ledger format" \
  --owner claude-code \
  --criteria "contract.yaml task schema extended with verified: bool, verified_at, verified_by" \
  --criteria "Ledger entry format documented in protocol/spec.md" \
  --criteria "Verify status added between in_progress and done in state machine"

superharness task create -p . \
  --id iter2.verify.implement \
  --title "Implement shux verify command in CLI" \
  --owner claude-code \
  --dependency iter2.verify.design \
  --criteria "superharness verify --id <task-id> --method <text> --result pass|fail works" \
  --criteria "Writes VERIFY entry to ledger.md (append-only)" \
  --criteria "Sets verified: true in contract.yaml on pass" \
  --criteria "Unit tests for verify command added"

superharness task create -p . \
  --id iter2.verify.gate \
  --title "Add verify gate to shux close — block if not verified" \
  --owner claude-code \
  --dependency iter2.verify.implement \
  --criteria "shux close <id> fails with clear error if verified: true not set" \
  --criteria "Error message includes: Run: shux verify <id>" \
  --criteria "Existing tests updated to reflect new close behavior"

superharness task create -p . \
  --id iter2.verify.hygiene \
  --title "Add verify coverage check to shux hygiene" \
  --owner claude-code \
  --dependency iter2.verify.gate \
  --criteria "shux hygiene warns on tasks closed without verification record" \
  --criteria "Warning includes list of affected task ids"

superharness task create -p . \
  --id iter2.verify.agents-md \
  --title "Add Verification Policy section to AGENTS.md" \
  --owner claude-code \
  --dependency iter2.verify.gate \
  --criteria "Policy states: test end-to-end before verify, not unit tests alone" \
  --criteria "Policy states: dev server must be running for UI tasks" \
  --criteria "Append-only rule respected (no rewrite of existing AGENTS.md content)"
```

---

## Iteration 3 — Feature Tracking at Init Time 🔴

**Goal:** Generate `features.json` at `shux init` so agents have a global definition of done.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter3.features.schema` | Define features.json schema and validation rules | todo |
| `iter3.features.init-prompt` | Add features.json generation to shux init flow | todo |
| `iter3.features.enforce` | Enforce append-only rule in shux hygiene | todo |

### shux task commands

```bash
superharness task create -p . \
  --id iter3.features.schema \
  --title "Define features.json schema and validation rules" \
  --owner claude-code \
  --criteria "Schema documented: id, category, description, steps[], passes: bool" \
  --criteria "JSON Schema file added to protocol/ for validation" \
  --criteria "Rule documented: only passes may change false→true, never edit/delete entries"

superharness task create -p . \
  --id iter3.features.init-prompt \
  --title "Add features.json generation to shux init flow" \
  --owner claude-code \
  --dependency iter3.features.schema \
  --criteria "shux init prompts for project type and expected features" \
  --criteria "Generates .superharness/features.json with all passes: false" \
  --criteria "Existing init behavior unchanged (contract.yaml, inbox.yaml still created)"

superharness task create -p . \
  --id iter3.features.enforce \
  --title "Enforce features.json append-only rule in shux hygiene" \
  --owner claude-code \
  --dependency iter3.features.init-prompt \
  --criteria "shux hygiene detects deleted or edited feature entries via git diff" \
  --criteria "Error shown if any feature id present in last commit is missing" \
  --criteria "Warning shown if description or steps changed on existing entry"
```

---

## Iteration 4 — Platform Parity: Linux systemd 🟡

**Goal:** Match the macOS launchd installer with a Linux counterpart.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter4.systemd.installer` | Write install-systemd-watcher.sh | todo |
| `iter4.systemd.readme` | Update README watcher section for macOS + Linux | todo |

### shux task commands

```bash
superharness task create -p . \
  --id iter4.systemd.installer \
  --title "Write install-systemd-watcher.sh mirroring launchd installer" \
  --owner claude-code \
  --criteria "Installs unit file to ~/.config/systemd/user/" \
  --criteria "Runs systemctl --user daemon-reload && enable && start" \
  --criteria "Accepts CONFIRM_NON_INTERACTIVE=yes env var" \
  --criteria "Script is idempotent (safe to run twice)"

superharness task create -p . \
  --id iter4.systemd.readme \
  --title "Update README watcher section to cover both macOS and Linux" \
  --owner claude-code \
  --dependency iter4.systemd.installer \
  --criteria "README shows both launchd and systemd install commands" \
  --criteria "Platform detection note added (uname check)"
```

---

## Iteration 5 — Documentation 🟡

**Goal:** Surface the two most unique features with worked examples.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter5.docs.discuss` | Write docs/DISCUSS.md with full worked example | todo |
| `iter5.docs.unattended` | Write docs/UNATTENDED.md with overnight run walkthrough | todo |

### shux task commands

```bash
superharness task create -p . \
  --id iter5.docs.discuss \
  --title "Write docs/DISCUSS.md with full worked example" \
  --owner claude-code \
  --criteria "Covers: two agents disagree, one opens discussion, other responds" \
  --criteria "Shows decisions.yaml entry after resolution" \
  --criteria "Shows how active discussion surfaces in shux status output" \
  --criteria "Under 400 lines"

superharness task create -p . \
  --id iter5.docs.unattended \
  --title "Write docs/UNATTENDED.md with overnight run walkthrough" \
  --owner claude-code \
  --criteria "Covers: launchd plist setup, poll interval, failure handling" \
  --criteria "Shows what ledger looks like the next morning" \
  --criteria "Covers: systemd equivalent for Linux" \
  --criteria "Under 300 lines"
```

---

## Iteration 6 — Visibility 🟢

**Goal:** Drive discovery with a comparison post contrasting superharness with Anthropic's approach.

| Task ID | Title | Status |
|---------|-------|--------|
| `iter6.blog.draft` | Draft comparison blog post → docs/blog-comparison-draft.md | todo |

### shux task commands

```bash
superharness task create -p . \
  --id iter6.blog.draft \
  --title "Draft comparison blog post: superharness vs Anthropic harness article" \
  --owner claude-code \
  --criteria "Covers: single-agent loops vs multi-agent coordination framing" \
  --criteria "Includes comparison table (session memory, task tracking, multi-agent, unattended)" \
  --criteria "Sections: what Anthropic got right, what superharness adds, core insight" \
  --criteria "Saved to docs/blog-comparison-draft.md, under 1200 words"
```

---

## Verification Checklist (per iteration)

| Check | Command |
|-------|---------|
| Protocol compliance | `shux hygiene` |
| Tests green | `pytest` (573+ passing) |
| iter1: install works | `pipx install superharness` from TestPyPI |
| iter2: gate active | `shux close <unverified-id>` must fail with actionable error |
| iter3: init generates features | `shux init` in fresh dir → `.superharness/features.json` with all `passes: false` |
| iter4: systemd install | `bash scripts/install-systemd-watcher.sh` on Linux |
