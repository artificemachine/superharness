# User Review (By CODEX)

Date and hour: 2026-03-10 02:05 CET
Reviewer: CODEX

## Summary
`superharness` is a practical tool for teams running Claude Code and Codex CLI in the same project. The core workflow works, but onboarding and trust/readiness signals need tightening before broad production adoption.

## Dimension scores
- 🟢 First impression: README explains the problem and value quickly.
- 🟡 Onboarding realism: quickstart still relies on manual YAML editing.
- 🟢 CLI ergonomics: command help and error output are clear and actionable.
- 🟢 Value proposition: cross-agent contract/queue/handoff model is concrete.
- 🟡 Failure surface: some invalid states warn instead of hard-failing.
- 🟡 Trust/readiness: CI exists and is pinned, but local test experience is not green-by-default.

## Top 3 strengths
1. Clear problem statement and command-oriented docs.
2. Good operational guardrails (`--print-only`, hygiene, doctor, watcher confirmations).
3. Security/test CI posture includes pinned action SHAs and pinned scanner version.

## Top 3 blockers
1. Manual contract editing in quickstart introduces first-run friction.
2. `enqueue` can proceed when task IDs are missing from contract (warn-only).
3. Local test confidence is mixed due to failing cases in current environment.

## Verdict
Adopt with caveats

## Recommended next steps
1. Add a one-command quickstart that creates a valid starter task automatically.
2. Add strict enqueue mode (or default) that rejects unknown task IDs.
3. Provide a single deterministic local bootstrap/test script for adopters.

---

# User Review (By Claude Sonnet 4.6)

Date and hour: 2026-03-10 CET
Reviewer: Claude Sonnet 4.6

## Summary
`superharness` is a multi-agent session handoff framework for Claude Code and Codex CLI. It solves a real problem — coordinating two AI agents on shared tasks without context loss — using shared contracts, a queue-based inbox, and append-only audit trails. The architecture is solid and security-hardened. The main barrier to adoption is first-run UX: the quickstart requires manual YAML editing and the install chain has too many steps before a working "hello world."

## Dimension Scores
| Dimension | Score | Notes |
|-----------|-------|-------|
| First Impression | 🟢 | README explains problem and workflow clearly in ~60 seconds. Command table is useful. |
| Onboarding | 🔴 | 6+ manual steps before first dispatch; requires ruby + python3 + claude CLI + codex CLI all pre-installed; manual YAML editing for initial task; no single bootstrap script. |
| CLI Ergonomics | 🟢 | All 14 commands have `--help`. `--print-only` is a great safety escape hatch. Error messages are actionable. `doctor` and `hygiene` commands help with self-diagnosis. |
| Value Proposition | 🟢 | Clear differentiation from generic plugins (superpowers). The contract/handoff/ledger model is novel and directly addresses cross-agent coordination. Target user is well-defined. |
| Failure Surface | 🟡 | `enqueue` is warn-only for missing task IDs. Stale recovery exists but requires manual invocation unless launchd is installed. Silent scope-guard failure if contract absent. |
| Trust & Production Readiness | 🟡 | CI is pinned and solid. ShipGuard SAST runs. No hardcoded secrets or paths in code. However, no coverage report, and test suite health varies by environment. v0.6 maturity is honest about it. |
| Docs & Support | 🟡 | QUICKSTART.md and ARCHITECTURE.md exist but are separate. No troubleshooting guide. No documented list of known error messages. CHANGELOG is maintained (47KB append-only). |

## Top 3 Strengths
1. **Security model is layered and explicit.** Scope guard, branch guard, 3-tier confirmation gates for unattended dispatch, and YAML safe loading — more hardening than most tools of this maturity.
2. **Operational visibility built-in.** `doctor`, `hygiene`, `monitor-ui`, and `--print-only` give users multiple ways to inspect state before committing to an action.
3. **Audit trail is first-class.** Every agent action, contract decision, and failure is append-only and queryable. This is the right default for agentic workflows.

## Top 3 Blockers (for adoption)
1. **Onboarding requires 4 external dependencies** (bash, ruby, python3, claude CLI, codex CLI) with no automated check or install path. First-run friction is high.
2. **No single bootstrap command.** The quickstart says "edit `.superharness/contract.yaml` manually" — this is a red flag for a tool positioning itself for automation. A `superharness task create` flow exists but is not surfaced in the quickstart.
3. **macOS-only unattended mode.** The background watcher (`launchd`) is macOS-specific. Linux is not supported. This silently caps the audience without a clear alternative for non-Mac users.

## Verdict
**Adopt with caveats**

Reason: The core protocol works and is well-hardened for v0.6. Best suited for solo developers or small teams already invested in the Claude Code + Codex CLI dual-agent workflow on macOS. Not ready for broader team adoption until onboarding and cross-platform support improve.

## Recommended Next Steps (for the maintainer)
- Add `superharness doctor --fix` that installs missing dependencies and validates the full setup.
- Rewrite the QUICKSTART to use `superharness task create` instead of manual YAML editing.
- Add `--strict` as the default for `enqueue` (reject unknown task IDs, not just warn).
- Add a Linux-compatible watcher option (cron or systemd service template).
- Publish a single `make test` or `./scripts/test-all.sh` that runs pytest + shell tests deterministically from a clean state.
- Add a `TROUBLESHOOTING.md` documenting the 5 most common errors and their fixes.
