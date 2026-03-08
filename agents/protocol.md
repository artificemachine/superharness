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
    reviewer: claude-code     # who reviews this task (peer review pattern)
    review_lenses: [security, architecture, error-handling]
    role: builder             # builder | reviewer | planner
    status: done
    branch: feat/auth-middleware
    output: "src/middleware/auth.ts created, 47 lines, tests passing"

  - id: auth-routes
    description: "Add login/logout/refresh endpoints"
    assigned_to: claude-code
    reviewer: codex-cli       # Codex reviews Claude's work
    review_lenses: [security, tests, api-contract]
    role: builder
    status: in_progress
    branch: feat/auth-routes

  - id: auth-integration
    description: "Integration testing across auth components"
    assigned_to: codex-cli
    reviewer: claude-code
    role: builder
    status: pending
    depends_on: [auth-middleware, auth-routes]

  - id: auth-docs
    description: "Update API documentation with auth endpoints"
    assigned_to: ollama        # simple task, local model is enough
    role: builder
    status: pending
    depends_on: [auth-integration]

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

## Agent Strengths & Weaknesses

Know what each agent is good at — and what to watch out for when reviewing its work.

### Claude Code
**Strengths:**
- Multi-turn reasoning — can hold complex architecture in context
- MCP tools — browser, Obsidian, Kubernetes, file system access
- User interaction — can ask clarifying questions mid-task
- Security review — good at spotting auth/access control issues
- Planning & orchestration — breaks big features into coherent tasks

**Weaknesses:**
- Can over-engineer — watch for unnecessary abstractions
- Verbose — may produce more code than needed
- Context rot — degrades on very long sessions (past ~60% context window)
- Can hallucinate APIs — verify imports and library calls exist

**When reviewing Claude's work, check for:** over-abstraction, unnecessary layers, verbose code that could be simpler, hallucinated dependencies.

### Codex CLI
**Strengths:**
- Fast sandboxed execution — isolated, no side effects on host
- Test-driven — strong at writing and running tests inline
- Focused — one task, one branch, no distractions
- Headless — can run as `codex exec` inside other workflows

**Weaknesses:**
- Limited context — no MCP, no browser, no user interaction
- Can miss big picture — optimizes locally, may not see architectural impact
- No memory between runs — each invocation starts fresh
- Simpler reasoning — may choose naive solutions for complex problems

**When reviewing Codex's work, check for:** naive implementations that miss edge cases, solutions that work locally but break the architecture, missing error handling, security shortcuts.

### Ollama (local models)
**Strengths:**
- Offline/private — no data leaves the machine
- Fast for simple tasks — no API latency
- Free — no token costs

**Weaknesses:**
- Smaller models — weaker reasoning, more mistakes
- No tools — just text in, text out
- Limited context window — can't hold large codebases

**When reviewing Ollama's work, check for:** everything. Treat as junior dev output. Verify all facts, logic, and code.

---

## How Each Agent Participates

| Agent | Reads | Writes | Strengths |
|-------|-------|--------|-----------|
| **Claude Code** | contract, handoffs, ledger | contract (create/plan), handoffs, ledger | Multi-turn reasoning, MCP tools, user interaction, architecture, security review |
| **Codex CLI** | contract (its tasks), handoffs | handoffs (when done), ledger (progress) | Fast sandboxed execution, focused implementation, test-driven, headless batch work |
| **Ollama** | contract (simple tasks), handoffs | handoffs (when done), ledger | Docs, formatting, simple generation, local-only/offline work |
| **Cowork** | contract, ledger, vault | contract (knowledge tasks), ledger | Research, vault maintenance, documentation |
| **Future agent** | contract, handoffs, ledger | Same pattern | Anything — protocol is agent-agnostic |

## Workflow Patterns

You (Maxime) are the tech lead. You choose which pattern to use per-task by setting `role` and `reviewer` fields in the contract.

### Pattern A: Peer Review (two seniors)

Both agents build AND review. Quality through mutual challenge.

```
You assign tasks in contract.yaml:
  Task 1 → Claude builds, Codex reviews
  Task 2 → Codex builds, Claude reviews

Claude (builds task 1)
    → writes handoff to Codex for review
Codex (reviews task 1, builds task 2)
    → writes review findings + handoff to Claude for review
Claude (reviews task 2, addresses review feedback on task 1)
    → writes updated handoff + review findings
```

**Use when:** you want quality, security review, catching blind spots. Both agents challenge each other's decisions. Neither rubber-stamps.

**Review rules for agents:**
- Read the diff, not just the summary
- Check edge cases, error handling, security
- Challenge architectural decisions — ask "why not X?"
- Log findings in the handoff, not just "approved"
- If you disagree with a decision, say so and explain why

### Pattern B: Hierarchical (plan → implement → review)

One agent plans and reviews, the other executes. Speed through specialization.

```
Claude Code (plans, creates contract, breaks into tasks)
    → assigns implementation tasks to Codex
Codex CLI (implements task by task)
    → writes handoff after each task
Claude Code (reviews each handoff, integrates)
    → approves or requests changes
```

**Use when:** the architecture is clear and you need fast execution. Claude's strength is reasoning + planning, Codex's strength is focused sandboxed coding.

### Pattern C: Subagent (Codex inside Claude Code)

Claude runs Codex headless for focused subtasks.

```
Claude Code creates contract
    → runs `codex exec` with task from contract
    → Codex returns output
    → Claude reviews inline, updates contract + ledger
```

**Use when:** task is small, isolated, and you don't want to context-switch between terminals.

---

## Directory Structure

In every project that uses multi-agent workflows:

```
project-root/
├── .superharness/
│   ├── contract.yaml          ← current active contract
│   ├── contracts/             ← archive of completed contracts
│   ├── handoffs/              ← handoff files between agents
│   ├── failures.yaml          ← cross-agent failure memory (persistent)
│   ├── decisions.yaml         ← cross-agent decision records (persistent)
│   ├── review-lenses/         ← project-specific review lenses (optional)
│   └── ledger.md              ← append-only activity log
├── CLAUDE.md                  ← Claude Code project config (from superharness template)
├── AGENTS.md                  ← Codex CLI project config (from superharness template)
└── ...
```

**Note:** `.superharness/` is project-local. superharness itself (the repo) defines the PROTOCOL. Each project gets its own instance of the protocol files.

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
