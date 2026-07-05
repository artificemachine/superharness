# Gemini Agent — superharness Protocol

You are `gemini-cli`, an agent in the superharness multi-agent framework.
Read this file fully before doing anything else.

---

## 0. Core Philosophy: Host, Not Agent

**superharness is a host (orchestrator), not a standalone agent runtime.**

- **Goal:** Provide the infrastructure (SQLite contracts, queue-based delegation, TDD lifecycle gates, and cross-agent memory) for professional agents to work safely and persistently.
- **Role:** It orchestrates external agents (`Claude Code`, `Codex CLI`, `Gemini CLI`). It does **not** implement its own standalone agent loop.
- **Dispatch:** Automation is achieved through `shux watch` (auto-dispatching tasks to external agents) or the MCP server, not by running superharness as a primary agent.
- **Non-Goal:** Do not attempt to add features that turn superharness into a standalone agent runtime. This would duplicate specialized agent functionality and bloat the core orchestration layer.

---

## 1. Find Your Task

```bash
cat .superharness/contract.yaml
```

Find the task with `owner: gemini-cli` and `status: todo` or `status: plan_approved`.
That is your task. Note its `id`.

Also check inbox for any item addressed to you:
```bash
cat .superharness/inbox.yaml
```

---

## 2. Read Context Before Starting

```bash
superharness recall --project . "<task keywords>"
cat .superharness/failures.yaml      # prior failures — avoid repeating them
cat .superharness/decisions.yaml     # prior architectural decisions
```

Read any handoff files addressed to `gemini-cli` in `.superharness/handoffs/`.

---

## 3. Task Lifecycle (Mandatory — Never Skip)

```
todo → plan_proposed → plan_approved → in_progress → report_ready → done
```

### If status is `todo`:
1. Write a plan handoff:
   ```bash
   superharness handoff-write --task <id> --phase plan --status plan_proposed \
     --from gemini-cli --to owner \
     --plan "scope and approach" \
     --tdd-red "failing tests to write first" \
     --tdd-green "minimal code to make them pass" \
     --tdd-refactor "cleanup after green" \
     --risks "open questions"
   ```
2. Set status to `plan_proposed` and **stop**. Wait for operator approval.

### If status is `plan_approved`:
1. Set status to `in_progress`:
   ```bash
   superharness task status --id <id> --status in_progress --actor gemini-cli --summary "starting implementation"
   ```
2. Implement following TDD: Red → Green → Refactor.
3. Run tests: `pytest tests/ -q --tb=short`
4. When done, write a report handoff:
   ```bash
   superharness handoff-write --task <id> --phase report --status report_ready \
     --from gemini-cli --to owner \
     --outcome "what was done" \
     --context "what next session needs to know"
   ```
5. Set status to `report_ready`:
   ```bash
   superharness task status --id <id> --status report_ready --actor gemini-cli --summary "<one-line outcome>"
   ```
6. **Stop. Do not close the task yourself.**

---

## 4. Rules

- Never commit directly to `main`. Create a feature branch: `git checkout -b feat/<id>`.
- Never run `git push` without `ALLOW_PUSH=1`.
- Never close a task — only the operator runs `superharness close`.
- CHANGELOG.md is append-only — add one line at EOF per commit.
- Never edit `.env`, credentials, or secrets.
- Run `pytest tests/ -q` before writing the report.

---

## 5. Stack

- Python (primary). Run `pip install -e .` if needed.
- CLI: `superharness <cmd>` or `shux <cmd>` (both always available).
- Tests: `pytest tests/ --ignore=tests/e2e -q`
- Lint/scan: `shipguard scan .`

---

## 5a. Global Install Hygiene (Critical)

- Never run `pipx install --editable` / `pipx install -e .` against the global `superharness`
  pipx venv (`~/.local/pipx/venvs/superharness`). This has regressed twice (2026-06-13,
  2026-07-05): it makes the live CLI and all 5 Claude Code hook scripts in
  `~/.claude/settings.json` resolve directly into this dev repo — deleting or breaking this
  checkout then breaks hooks globally.
- For local dev-testing, use a repo-local venv: `python -m venv .venv && .venv/bin/pip install -e .`.
- If this regresses: `pipx uninstall superharness && pipx install <wheel-or-pypi>` (non-editable),
  then `shux install-hooks`.

---

## 6. Commands Reference

| Command | Purpose |
|---------|---------|
| `shux contract` | Show all tasks and statuses |
| `shux task status --id <id> --status <s> --actor gemini-cli --summary "<s>"` | Advance task status |
| `shux handoff-write` | Write plan or report handoff YAML |
| `shux recall --project . "<keywords>"` | Search past handoffs |
| `shux verify --id <id> --method "<how>" --result pass` | Record verification |

---

## 7. When Done

After writing the report and setting status to `report_ready`:
- Append a CHANGELOG.md line.
- Commit on your feature branch.
- Stop. The operator reviews and closes.

## Self-Improvement Health Check

Every 3-5 sessions or when starting a new task, verify the self-learning systems are alive:

```bash
shux profile show                          # behavioral profile — should have data
shux memory-roots list                     # global memory scan roots — should be configured
shux daemon status                         # watcher/daemon — should be running

# Deep check:
ls ~/.config/superharness/behavioral/      # profile files — should exist
ls ~/.config/superharness/memory/          # global memory — should have entries
cat .superharness/memory/pitfalls.md       # project learnings
```

If any system is empty or down, report it to the operator with: what's missing, what should be there, and the fix command (e.g. `shux daemon start`).
