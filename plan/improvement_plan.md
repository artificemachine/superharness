# Superharness Improvement Plan

**Date:** 2026-03-12
**Version:** v0.7.0 → v0.8.0
**Author:** Architecture review (Claude + Rocha)

---

## Context

Superharness is a cross-agent coordination protocol for Claude Code and Codex CLI. At v0.7.0, the core protocol is stable: contracts, handoffs, ledger, failure memory, decision records, inbox-based dispatch, background watcher, monitor-ui, and agent-install module all work. The project has ~8,200 lines of operational code and ~7,600 lines of tests.

This plan identifies what to build next, in what order, and what to explicitly skip. It draws on patterns observed in OpenClaw (persistent memory, heartbeat/proactive behavior, identity separation) while preserving superharness's identity as a lightweight coordination protocol — not an agent framework.

---

## Guiding Principle

Superharness coordinates agents. It does not try to be one. Every improvement should make the coordination smarter, not replace what the agents already do well.

---

## Codex Review Notes (2026-03-12)

Incorporated from Codex CLI review:

1. **Phase 1c ships first** — profile wiring unlocks visible behavior immediately; do not defer behind recall or heartbeat.
2. **Heartbeat: built-in IDs only (v1)** — map `id` values to vetted hardcoded commands server-side; `command:` field is ignored unless `id` is in the allowlist. Arbitrary shell-in-YAML is a future option, not the default.
3. **Status MVP scope** — exact fields defined below; fallback behavior for missing files specified explicitly.
4. **Acceptance tests per phase** — each phase has a "Done when" checklist before implementation bullets.

---

## Phase 1 — Make the Install Path Real

The agent-install module (INSTALL-AGENT.md, detect.rb, profile.yaml, --from-profile/--detect) landed but has not been tested by a live agent on a fresh project. This phase closes that gap.

**Done when:**
- [ ] `pytest tests/unit/test_profile.py` passes (profile.rb reads all fields, returns defaults for missing)
- [ ] `pytest tests/unit/test_profile_delegate_wiring.py` passes (autonomy maps to correct env vars)
- [ ] `pytest tests/unit/test_profile_task_wiring.py` passes (primary_agent used as default owner)
- [ ] `pytest tests/unit/test_profile_contract_today_wiring.py` passes (team_size affects output format)
- [ ] Live agent install test completed on one real project

### 1a. Test coverage for new code

Write unit tests for:

- `engine/detect.rb` against mock project directories (Node project, Python project, Rust project, non-git project, empty directory)
- `init-project.sh --from-profile` producing correct `.superharness/profile.yaml`, `CLAUDE.md`, and `AGENTS.md`
- `init-project.sh --detect` auto-populating project name, stack, and status from detect.rb output
- Edge cases: profile with missing `project_name` (falls back to basename), detect.rb on a project with no recognizable files (returns empty stack)

Add to `tests/unit/test_detect.py` and extend `tests/unit/test_init_project.py`.

### 1b. Live agent install test

Take a real project (not superharness itself), start a Claude Code session, and say "install superharness in this project." Point the agent at the README. Document where the agent gets confused, asks unnecessary questions, or fails to follow INSTALL-AGENT.md. Fix the document based on what actually happens.

This is a manual test, not automatable — but it's the most important validation of the entire module.

### 1c. Profile wires into runtime

Right now `profile.yaml` is written and stored but nothing reads it at runtime. Wire the three highest-value fields:

- **`autonomy` → `delegate.sh`**: Read `.superharness/profile.yaml`, map `autonomous` to setting both `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES` and `SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES`; map `supervised` to setting only `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES`; map `approval-gated` to leaving both unset (default).
- **`primary_agent` → `task.sh`**: When `--owner` is not specified on `task create`, default to the `primary_agent` value from profile.yaml.
- **`team_size` → `contract-today.sh`**: When `team_size` is `solo`, use compact output (no owner column). When `small` or `team`, show owner column and suggest delegation.

Each wiring is a small change (read YAML, set variable, conditional logic). Add a helper in `engine/` that reads profile.yaml and returns a single field, so every script uses the same pattern:

```bash
AUTONOMY="$(ruby "$SCRIPT_DIR/../engine/profile.rb" autonomy)"
```

---

## Phase 2 — Memory: `superharness recall`

**Done when:**
- [ ] `pytest tests/unit/test_recall.py` passes (keyword search, recency sort, --since filter, no-results case)
- [ ] `superharness recall --project . "keyword"` returns output in < 1s on a project with 50+ handoffs
- [ ] CLAUDE.md.template and AGENTS.md.template include `superharness recall` in "Before Starting Work"

The highest-value new feature. Every long-running project accumulates context in handoffs that nobody can find later. Agents start each session with amnesia about what happened three tasks ago.

### 2a. `engine/recall.rb`

A Ruby script that searches `.superharness/handoffs/` YAML files and `ledger.md` by keyword.

Behavior:

- Accept one or more search terms as arguments
- Scan all `.yaml` and `.md` files in `handoffs/`
- Scan `ledger.md`
- For each match, return: file name, task ID (from YAML `task_id` field or filename), date, agent, and the matching line with surrounding context (±2 lines)
- Sort results by relevance (keyword frequency in the file) then by recency (newest first)
- Output one line per match in compact format

No new dependencies. Ruby stdlib only. No SQLite, no vector store, no embeddings.

### 2b. `superharness recall` command

Shell wrapper routing to `engine/recall.rb`:

```bash
superharness recall --project . "authentication"
superharness recall --project . "authentication" "migration"
superharness recall --project . --since 7d "deploy"
```

Output format:

```
2026-03-10  claude-code  watcher-timeout-and-lock-guard
  "Added --launcher-timeout to inbox-dispatch.sh (portable perl-based process-group kill)"

2026-03-08  codex-cli    ci-parity-entrypoints
  "Entrypoint auto-discovery via --list-entrypoints"
```

Designed to be piped into agent context or read by a human.

### 2c. Agent integration

Update `protocol/templates/CLAUDE.md.template` and `AGENTS.md.template` to include:

```markdown
## Before Starting Work
- Run `superharness recall "KEYWORDS"` with terms related to your task
- Check for prior decisions, failures, or context from earlier sessions
```

This turns handoffs from write-only archives into searchable institutional memory.

---

## Phase 3 — Heartbeat: Proactive Watcher

**Done when:**
- [ ] `pytest tests/unit/test_heartbeat.py` passes (enabled/disabled, interval elapsed/not, state update, unknown ID skipped)
- [ ] `init-project.sh` creates `.superharness/heartbeat.yaml` with stale-recovery enabled
- [ ] Unknown `id` in heartbeat.yaml is logged and skipped (not executed)

The watcher (`inbox-watch.sh`) already runs on a loop but is purely reactive — it only dispatches items already in the queue. It never looks around and notices problems on its own.

### 3a. `.superharness/heartbeat.yaml`

A file listing proactive checks the watcher should run on each cycle.

**Security constraint (Codex review):** The `id` field maps to a hardcoded vetted command in `scripts/heartbeat.sh`. The `command:` field in YAML is documentation only and ignored at runtime — arbitrary shell-in-YAML is not executed. This prevents YAML injection from escalating to code execution.

Allowed built-in check IDs (v1): `stale-recovery`, `idle-warning`, `hygiene-check`.

```yaml
# Proactive checks — evaluated by the watcher after each dispatch pass
# Note: 'command' field is documentation only. Actual commands are hardcoded in heartbeat.sh.
checks:
  - id: stale-recovery
    description: Recover tasks stuck longer than the timeout
    interval_minutes: 60
    enabled: true

  - id: idle-warning
    description: Warn if no ledger activity in 48 hours
    interval_minutes: 1440
    enabled: true

  - id: hygiene-check
    description: Run protocol hygiene validation
    interval_minutes: 720
    enabled: false
```

### 3b. Heartbeat runner

Add a heartbeat pass to `inbox-watch.sh` (or a separate `scripts/heartbeat.sh` called by the watcher):

- After the normal dispatch pass, read `heartbeat.yaml`
- For each enabled check, look up the `id` in the built-in allowlist (not the YAML `command:` field)
- Compare `interval_minutes` against last run timestamp (stored in `.superharness/heartbeat-state.yaml`)
- If interval has elapsed, run the vetted command and update the timestamp
- Log output to watcher log
- Unknown `id` values are logged and skipped — never executed

### 3c. Default heartbeat template

Add `protocol/templates/heartbeat.yaml` with stale recovery and idle detection pre-configured. `init-project.sh` creates it alongside the other protocol files. All checks default to `enabled: false` except stale recovery.

---

## Phase 4 — Polish for First External User

**Done when:**
- [ ] `pytest tests/unit/test_interactive_init.py` passes (piped input, auto-detect used, profile written)
- [ ] LICENSE (MIT) and CONTRIBUTING.md exist in repo root
- [ ] `pytest tests/unit/test_status.py` passes (all MVP fields, all fallback cases)

These are adoption blockers — things that prevent anyone outside Rocha from using the project.

### 4a. `superharness init --interactive`

A shell-driven questionnaire (not agent-driven) for humans who don't want to type positional arguments:

```
$ superharness init --interactive

superharness — interactive setup
================================

Detected: Python/Docker project, GitHub remote, solo developer

? Autonomy level (how much oversight for agents?)
  1. autonomous — agents act without asking
  2. supervised — agents explain, then proceed
  3. approval-gated — agents wait for explicit approval
> 2

? What are you working on right now? (one sentence)
> Migrate the API from Express to Fastify

? Enable background watcher? (macOS launchd) [y/N]
> n

Initializing...
Done. Run 'superharness contract today' to see your first task.
```

Uses `detect.rb` for auto-detection, asks only the 2-3 questions that can't be inferred, writes profile.yaml, runs init. Plain `read -p` prompts — no TUI library, no curses.

### 4b. LICENSE and CONTRIBUTING.md

The public readiness audit flagged these as missing. Without them, nobody from outside will contribute or even feel confident using the project.

- LICENSE: MIT (standard for dev tools)
- CONTRIBUTING.md: How to run tests, commit conventions, PR expectations. Keep it under 50 lines.

### 4c. `superharness status`

One command that shows the project dashboard in the terminal.

**MVP fields (Codex review — define now to prevent scope creep):**

```
$ superharness status --project .

superharness v0.8.0 — my-cool-api
==================================
Contract: v08-reliability (active)
Goal:     Harden watcher reliability

Tasks:  3 pending · 1 running · 2 done · 1 failed
        Next: structured-error-logging (codex-cli)

Last activity: 2026-03-12 — "Completed watcher timeout guard"
Watcher:       running (PID 12345, interval 30s)
Profile:       supervised · claude-code primary · solo
```

**Fallback behavior for missing files:**
- No `contract.yaml` → show `Contract: (none — run superharness init)`
- No `ledger.md` → show `Last activity: (none)`
- No `profile.yaml` → show `Profile: (default — no profile.yaml)`
- No watcher heartbeat file → show `Watcher: unknown (run superharness doctor)`
- Watcher heartbeat older than 3× interval → show `Watcher: stale`

Combines `contract.yaml`, watcher heartbeat file, profile.yaml, and last line of `ledger.md`. No new infrastructure — just aggregation.

---

## Phase 5 — Identity Separation

**Done when:**
- [ ] `pytest tests/unit/test_soul_md.py` passes (init creates SOUL.md, CLAUDE.md references it, skipped if exists)
- [ ] CLAUDE.md.template and AGENTS.md.template reference `Read SOUL.md for identity and constraints`

Low urgency, architecturally clean. Do it when you're already touching templates for another reason.

### 5a. `SOUL.md`

Split "who am I and what are my constraints" out of CLAUDE.md into a separate `SOUL.md` file:

```markdown
# Soul — Project Owner

## Operating Constraints
- Limited weekly bandwidth
- Ship > plan. One task per session.

## Guardrails
- Never edit .env, credentials, or secrets
- Never push directly to main
- Run required checks before handoff/commit
```

Both CLAUDE.md and AGENTS.md reference SOUL.md. The agent config files become purely project-technical: test commands, directories, conventions.

### 5b. Update templates and init

- Move `identity-core.md` content into a `SOUL.md.template`
- Update `init-project.sh` to generate `SOUL.md` alongside CLAUDE.md and AGENTS.md
- Update both agent templates to include `Read SOUL.md for identity and constraints`

---

## What to Explicitly Skip

These are patterns observed in OpenClaw or suggested in prior reviews that would hurt superharness if adopted:

| Pattern | Why Skip |
|---------|----------|
| **Gateway / multi-channel routing** | Superharness coordinates coding agents, not chat apps. The "gateway" is `delegate.sh` → agent CLI. Adding WhatsApp/Telegram routing is a different product. |
| **ReAct loop / custom reasoning** | The agents already reason. Don't rebuild Claude Code's brain. |
| **SQLite + vector embeddings** | Overengineered for a local dev tool. `grep` over YAML handoffs is sufficient until 500+ handoffs, which takes years. Graduate to semantic search only if recall proves insufficient. |
| **Docker packaging** | Shell scripts that run everywhere bash runs is a feature. Don't add a container dependency. |
| **Plugin marketplace** | Zero external users means zero plugin authors. Premature. |
| **Web dashboard rewrite** | monitor-ui works. Don't gold-plate it. |
| **Multi-agent beyond 2** | The protocol supports N agents in theory, but real-world usage is Claude Code + Codex CLI. Don't abstract for a third agent that doesn't exist yet. |
| **Cloud sync / remote state** | File-based local state is a feature. Network-aware locking and remote sync introduce failure modes that don't belong in a dev tool. |

---

## Success Criteria

The plan is successful when:

1. An agent (Claude Code or Codex) can install superharness on a fresh project by reading the README — without human terminal interaction beyond answering two questions
2. `superharness recall` returns relevant context from past sessions, and agents use it before starting new tasks
3. The watcher proactively recovers stale tasks without being told to
4. A developer who has never seen superharness can go from `git clone` to first delegation in under 5 minutes using `superharness init --interactive`
5. `superharness status` gives a complete project picture in one command