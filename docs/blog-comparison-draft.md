# What Anthropic Gets Right About AI Agent Harnesses — and What's Missing

*A comparison between Anthropic's "Effective Harnesses for Long-Running Agents" and superharness.*

---

## The Anthropic Article in 60 Seconds

In November 2025, Anthropic published advice on building harnesses for long-running agents. Their key points:

- **Give agents memory** between sessions (files, summaries, context)
- **Use checkpoints** so agents can recover from failures
- **Keep humans in the loop** with approval gates
- **Design for idempotency** so retries don't cause harm

This is excellent advice. If you're building a single-agent loop, follow every word of it.

But there's an assumption baked into the article: **you're running one agent.**

## What Happens With Two?

The moment you introduce a second agent — say Claude Code handles architecture while Codex CLI handles implementation — new problems appear that single-agent harnesses don't address:

1. **Session memory isn't shared.** Each agent has its own context. Agent A finishes work, but Agent B starts fresh with no knowledge of what happened.
2. **There's no task contract.** Who owns what? What's done? What's blocked? Each agent guesses based on whatever files it reads.
3. **Decisions are invisible.** Agent A makes a design choice. Agent B contradicts it. No one notices until the code breaks.
4. **There's no audit trail across agents.** You can see what one agent did in its session log, but correlating actions across two agents requires manual archaeology.

## The Core Insight

Anthropic's article solves **session continuity** — helping one agent work across multiple sessions.

superharness solves **agent coordination** — helping multiple agents work on the same project without conflicting.

These are complementary, not competing. But if you use multiple agents (which is increasingly common), session continuity alone isn't enough.

## Comparison Table

| Capability | Anthropic harness approach | superharness |
|-----------|---------------------------|--------------|
| Session memory | Agent-specific files, summaries | Shared contract + handoffs + ledger |
| Task tracking | Ad hoc (files, comments) | Structured contract.yaml with state machine |
| Multi-agent coordination | Not addressed | First-class: handoffs, ownership, discussions |
| Unattended execution | Mentioned as use case | Built-in: launchd/systemd watcher with queue |
| Decision records | Not addressed | decisions.yaml + structured discussion protocol |
| Failure memory | Mentioned (checkpoints) | failures.yaml — cross-agent, append-only |
| Verification before close | Not addressed | verify → close gate with ledger audit |
| Human approval gates | Recommended | Configurable: autonomous / supervised / approval-gated |
| Model routing | Not addressed | Auto-classification: route tasks to cheapest capable model |

## What Anthropic Got Right

**Everything about single-agent ergonomics.** Their advice on memory, checkpoints, and idempotency is sound. superharness implements all of it:

- **Memory**: shared contract, handoffs, ledger, and decisions files persist across sessions
- **Checkpoints**: task status machine (todo → in_progress → done/failed) with inbox recovery for stale items
- **Idempotency**: append-only ledger, atomic YAML writes, inbox deduplication
- **Human-in-the-loop**: three autonomy levels configurable per project

## What superharness Adds

### 1. Coordination Protocol

Two agents can work on the same project because they share:
- A **contract** defining tasks, owners, and acceptance criteria
- **Handoff files** that transfer context between agents
- A **ledger** recording every action by every agent
- A **discussion protocol** for structured disagreements

### 2. Structured Verification

Tasks can't be closed without verification. The `verify → close` gate ensures agents prove their work before marking tasks done — not just for one agent, but as a cross-agent policy.

### 3. Unattended Multi-Agent Orchestration

The watcher doesn't just retry one agent. It dispatches from a shared queue to whichever agent owns each task, handles failures per-agent, and recovers stale items.

### 4. Cost-Aware Model Routing

Tasks are automatically classified and routed to the cheapest model that can handle them. A README fix goes to Haiku; an architecture redesign goes to Opus. This is invisible to the agent — superharness handles it at delegation time.

## Who Should Use What

**Use Anthropic's approach if:**
- You run a single agent
- Your tasks are independent (no cross-agent dependencies)
- You're building a custom harness from scratch

**Use superharness if:**
- You use Claude Code and/or Codex CLI
- You hand off tasks between agents or sessions
- You want an audit trail of what each agent did and decided
- You run agents unattended overnight
- You want cost-optimized model routing

## Try It

```bash
pipx install superharness
cd your-project
superharness init --interactive
superharness doctor --project .
```

Then open Claude Code or Codex CLI and type `shux contract` to see your tasks.

---

*superharness is open source: [github.com/celstnblacc/superharness](https://github.com/celstnblacc/superharness)*
