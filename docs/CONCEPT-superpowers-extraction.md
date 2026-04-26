# superpowers → superharness: Extraction Analysis

Source: https://github.com/obra/superpowers (167k stars, 14.7k forks, created Oct 2025)

---

## What superpowers is

A collection of composable `SKILL.md` files that coding agents (Claude Code, Codex, Cursor, Gemini CLI, Copilot) load as context. Each skill encodes a disciplined engineering process: brainstorming, spec writing, plan writing, subagent dispatch, TDD enforcement, code review, debugging, branch finishing. Skills trigger automatically when the agent detects the relevant situation. No user ceremony required.

## Why it went viral

It solves the most painful agent problem: agents that default to "just write code" while skipping tests, drifting from specs, and self-reviewing poorly. The appeal is zero user ceremony. Drop SKILL.md files into your context and the agent picks up disciplined engineering automatically. Two specific mechanics are cited most:

- Two-stage review per task (spec compliance first, then code quality)
- Fresh subagent per task with zero context pollution

---

## Extractable ideas for superharness

### 1. Context manifest in task YAML

**Superpowers pattern:** Each task constructs exactly the context the implementer subagent needs — no more, no less.

**superharness gap:** Handoffs dump everything. Agents in a dispatch run get context-bloated or context-starved depending on how the handoff was written.

**Concrete addition:** Add a `context_manifest` field to the task YAML:

```yaml
context_manifest:
  include:
    - .superharness/handoffs/plan-<id>.yaml
    - src/core/dispatch.py
  exclude:
    - .superharness/handoffs/old-*.yaml
```

This is the highest-leverage extraction. Formalizing what context to inject per task would improve dispatch quality without changing the contract structure.

---

### 2. Two-stage review gate before `shux close`

**Superpowers pattern:** Every task passes two sequential review passes before it can be closed: spec compliance first, then code quality.

**superharness gap:** A single `verify` step before `shux close`. No distinction between "did it do what the acceptance criteria said" vs "is the code good."

**Concrete addition:** Enforce two review phases in the task lifecycle:

```
report_ready → review_spec → review_quality → done
```

`shux close` is blocked until both `review_spec` and `review_quality` are logged in the ledger.

---

### 3. Skill files with `when_to_use` decision graph

**Superpowers pattern:** Each phase (plan, implement, review, close) is a self-contained `SKILL.md` with an explicit `when_to_use` decision block that agents parse.

**superharness gap:** Phase rules live as prose in `CLAUDE.md`. Agents must infer when to apply which phase from unstructured text.

**Concrete addition:** Extract each superharness phase into a small skill file:

```
docs/skills/SKILL-plan.md
docs/skills/SKILL-implement.md
docs/skills/SKILL-review.md
docs/skills/SKILL-close.md
```

Each file starts with a structured `when_to_use` block and a decision flowchart. Agents load the relevant skill file for each dispatch phase rather than parsing the entire `CLAUDE.md`.

---

### 4. Mandatory `execution_skill` field in task YAML

**Superpowers pattern:** Every plan doc starts with a required header block telling the agent which skill to use to execute it. No ambiguity about dispatch method.

**superharness gap:** Tasks don't declare how they should be dispatched. The agent picks sdk vs cli vs codex based on context inference.

**Concrete addition:** Add `execution_skill` to the task YAML:

```yaml
execution_skill: sdk          # sdk | cli | codex
```

`shux delegate` validates this field is present before enqueuing.

---

### 5. Enforced scope pre-flight (not advisory warning)

**Superpowers pattern:** The `writing-plans` skill refuses to proceed if the spec spans independent subsystems and forces decomposition first. Hard gate, not a warning.

**superharness gap:** The Task Scope Rule (>3 acceptance criteria = decompose) is documented as an advisory warning in `CLAUDE.md`. Agents routinely proceed without decomposing.

**Concrete addition:** Make decomposition a hard gate on the `plan_approved` transition:

- `shux plan-approve <id>` checks acceptance criteria count and touched-file count
- If >3 AC or >4 files: `plan_approved` is blocked, status stays `plan_proposed`
- Agent must submit subtasks with `blocked_by` links before approval proceeds

---

### 6. In-session live task tracking

**Superpowers pattern:** Agents track task progress in-session via `TodoWrite` (Claude's built-in live task tool). Step-by-step visibility without polling a file.

**superharness gap:** `contract.yaml` state is async and file-based. There is no live in-session visibility into what step the agent is on during a dispatch run.

**Concrete addition:** Each dispatch run mirrors step transitions into a session log:

```
.superharness/runs/<task-id>-<timestamp>.log
```

One line per step, written as the agent executes. The dashboard tails this file for live progress without waiting for a full handoff write.

---

## Priority order

| Priority | Idea | Effort | Impact |
|----------|------|--------|--------|
| 1 | Context manifest in task YAML | Medium | Very high — fixes context pollution on every dispatch |
| 2 | Enforced scope pre-flight | Low | High — closes the most common CLAUDE.md advisory bypass |
| 3 | Two-stage review gate | Low | High — catches spec drift before code quality review |
| 4 | Skill files with decision graph | High | Medium — improves agent composability long term |
| 5 | `execution_skill` field | Low | Medium — removes dispatch ambiguity |
| 6 | In-session live tracking | Medium | Medium — dashboard UX improvement |

---

*Analysis date: 2026-04-26*
