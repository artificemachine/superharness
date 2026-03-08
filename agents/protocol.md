# Cross-Agent Communication Protocol

How Claude Code, Codex CLI, Ollama, and any future agent share context, split tasks, and hand off work without losing information.

---

## The Problem

Agents don't talk to each other. Claude Code doesn't know what Codex just did. Codex can't read Claude's conversation. Ollama has no memory between runs. Each session starts from zero unless something bridges the gap.

Current bridges:
- Git (commits, branches, diffs) — works but coarse-grained
- Files (CLAUDE.md, AGENTS.md) — config, not state
- Your head — you remember, you re-explain, you lose context

superharness replaces "your head" with a protocol that any agent can read and write.

---

## The Shared Language

Three file types form the communication layer. Any agent that reads and writes these can participate in a superharness workflow, regardless of what model it runs.

### 1. Contract — What needs to happen

```yaml
# .superharness/contract.yaml
id: feat-auth-module
created: 2026-03-08
created_by: claude-code
status: in_progress  # draft | in_progress | review | done | blocked

goal: "Implement JWT authentication for the API"

tasks:
  - id: auth-middleware
    description: "Create Express middleware for JWT validation"
    assigned_to: codex-cli    # claude-code | codex-cli | ollama | any
    status: done
    branch: feat/auth-middleware
    output: "src/middleware/auth.ts created, 47 lines, tests passing"

  - id: auth-routes
    description: "Add login/logout/refresh endpoints"
    assigned_to: codex-cli
    status: in_progress
    branch: feat/auth-routes

  - id: auth-review
    description: "Cross-agent review of auth implementation"
    assigned_to: claude-code   # different agent reviews
    status: pending
    depends_on: [auth-middleware, auth-routes]

  - id: auth-docs
    description: "Update API documentation with auth endpoints"
    assigned_to: ollama        # simple task, local model is enough
    status: pending
    depends_on: [auth-review]

decisions:
  - what: "JWT over session tokens"
    why: "Stateless, works with microservices, Codex has strong JWT patterns"
    date: 2026-03-08
    by: claude-code

  - what: "RS256 over HS256"
    why: "Asymmetric keys allow token verification without sharing secrets"
    date: 2026-03-08
    by: claude-code

failures:
  - what: "Tried passport.js first"
    why_failed: "Over-engineered for our use case. Raw jsonwebtoken is simpler."
    date: 2026-03-08
    by: codex-cli
```

**Rules:**
- One contract per feature/epic. Not per session, not per task.
- Any agent can read the contract to understand what's happening.
- Any agent can update its own task status and output.
- Decisions and failures accumulate — this IS the decision journal + failure memory.

### 2. Handoff — Passing the baton

```yaml
# .superharness/handoffs/2026-03-08-auth-middleware.yaml
from: codex-cli
to: claude-code
date: 2026-03-08T22:30:00
contract: feat-auth-module
task: auth-review

context:
  branch: feat/auth-middleware
  files_changed:
    - src/middleware/auth.ts (new, 47 lines)
    - src/middleware/auth.test.ts (new, 83 lines)
    - src/types/auth.ts (new, 12 lines)
  tests: "12/12 passing"
  build: "clean"

what_was_done: |
  Created JWT validation middleware. Extracts token from Authorization header,
  validates with RS256 public key, attaches decoded user to req.user.
  Handles expired tokens, malformed tokens, missing tokens with distinct error codes.

what_to_check: |
  - Edge case: what happens with clock skew on token expiry?
  - Security: is the public key loading secure? Currently reads from env var.
  - Integration: does it play well with the existing error handler middleware?

do_not:
  - Don't refactor the error handler. That's a separate task.
  - Don't add rate limiting. Out of scope for this contract.
```

**Rules:**
- Written by the agent that just finished work.
- Read by the next agent before starting.
- Includes what to check AND what NOT to do (scope guard).
- References the contract so context is always recoverable.

### 3. Ledger — What happened over time

```markdown
# .superharness/ledger.md

## 2026-03-08

### 22:00 — claude-code — Planning
- Created contract: feat-auth-module
- Decision: JWT over session tokens (stateless, microservices-ready)
- Decision: RS256 over HS256 (asymmetric key verification)
- Assigned: auth-middleware → codex-cli, auth-routes → codex-cli

### 22:15 — codex-cli — Implementation
- Started: auth-middleware
- Failure: passport.js too heavy, switched to raw jsonwebtoken
- Completed: auth-middleware (47 lines, 12 tests passing)
- Handoff → claude-code for review

### 22:30 — claude-code — Review
- Reviewed: auth-middleware
- Finding: clock skew not handled, added 30s leeway
- Finding: public key should load from file, not env var (rotation)
- Approved with changes

### 22:45 — codex-cli — Implementation
- Started: auth-routes
- In progress...
```

**Rules:**
- Append only. Never edit previous entries.
- One line per action. Not prose. Scannable.
- Any agent appends when it starts or finishes work.
- The ledger IS the session log. /upvault can pull from it.

---

## How Each Agent Participates

| Agent | Reads | Writes | Best For |
|-------|-------|--------|----------|
| **Claude Code** | contract, handoffs, ledger | contract (create/plan), handoffs (review results), ledger | Planning, architecture, review, orchestration |
| **Codex CLI** | contract (its tasks), handoffs (from previous agent) | handoffs (when done), ledger (progress) | Implementation, batch work, isolated execution |
| **Ollama** | contract (simple tasks), handoffs | handoffs (when done), ledger | Docs, formatting, simple generation, local-only work |
| **Cowork** | contract, ledger, vault | contract (knowledge tasks), ledger | Research, vault maintenance, documentation |
| **Future agent** | contract, handoffs, ledger | Same pattern | Anything — protocol is agent-agnostic |

---

## Directory Structure

In every project that uses multi-agent workflows:

```
project-root/
├── .superharness/
│   ├── contract.yaml          ← current active contract
│   ├── contracts/             ← archive of completed contracts
│   ├── handoffs/              ← handoff files between agents
│   └── ledger.md              ← append-only activity log
├── CLAUDE.md                  ← Claude Code project config
├── AGENTS.md                  ← Codex CLI project config
└── ...
```

**Note:** `.superharness/` is project-local. superharness itself (the repo) defines the PROTOCOL. Each project gets its own instance of the protocol files.

---

## Workflow Examples

### Example 1: Solo evening session (one agent)
```
1. Claude Code reads contract → picks next task
2. Implements → updates ledger → updates contract status
3. Writes handoff (even if tomorrow-you is the "next agent")
4. /upvault
```
No multi-agent needed. The protocol still captures state for continuity.

### Example 2: Claude plans, Codex implements
```
1. Claude Code creates contract → breaks feature into tasks
2. Claude assigns implementation tasks to Codex
3. Codex reads contract → implements task → writes handoff + ledger
4. Claude reads handoff → reviews → writes ledger
5. Repeat for next task
```

### Example 3: Codex as subagent inside Claude Code
```
1. Claude Code creates contract
2. Claude runs `codex exec` with task description from contract
3. Codex writes output → Claude captures it
4. Claude updates contract + ledger
5. Claude reviews output, assigns next task
```

### Example 4: Three agents, parallel work
```
1. Claude creates contract with 3 independent tasks
2. Task A → Codex (branch: feat/task-a, worktree isolation)
3. Task B → Codex (branch: feat/task-b, worktree isolation)
4. Task C → Ollama (local, simple doc task)
5. Each writes handoff when done
6. Claude reads all handoffs → cross-reviews → merges
```

---

## Relationship to superharness

The protocol is DEFINED in `superharness/agents/protocol.md` (this file).
The protocol is INSTANTIATED in each project as `.superharness/`.
The protocol is AGENT-AGNOSTIC — any LLM that can read/write YAML and markdown can participate.

This is what makes superharness different from a Claude Code plugin or a Codex config. It's the shared language between ALL your agents.

---

## Rules

1. **Contract is the source of truth.** Not the conversation, not the git log, not your memory.
2. **Handoffs are mandatory.** Even if the "next agent" is yourself tomorrow.
3. **Ledger is append-only.** Never edit. Only add.
4. **Scope is in the contract.** If it's not in the contract, it's not this session's job.
5. **Failures get logged.** What didn't work is as valuable as what did.
6. **Decisions get logged with WHY.** The "what" is in the code. The "why" is in the contract.
