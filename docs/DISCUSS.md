# Multi-Agent Discussions

superharness includes a structured discussion protocol that lets two agents debate a decision before either acts on it. This prevents one agent from making a unilateral choice that the other agent (or a human reviewer) would disagree with.

## When to Use Discussions

Use `shux discuss` when:
- A design decision affects both agents' work
- Two approaches are plausible and you want structured tradeoff analysis
- You need an auditable record of *why* a decision was made

Do **not** use discussions for:
- Simple tasks with obvious answers
- Decisions that only affect one agent's scope
- Anything time-critical (discussions add latency)

## Worked Example: Database Schema Change

Two agents disagree about how to add a `tags` field to a project model.

### Step 1 — Start the Discussion

```
shux discuss start --topic "How to store tags on the Project model" \
  --owners claude-code,codex-cli --max-rounds 3
```

This creates:
```
.superharness/discussions/discuss-tags-on-project/
├── state.yaml       # topic, owners, max_rounds, status
└── (round files appear as agents respond)
```

### Step 2 — Round 1: Each Agent States Their Position

The watcher (or manual delegation) dispatches each agent with a discussion prompt. Each agent reads the topic and writes their position:

**Claude Code writes `round-1-claude-code.yaml`:**
```yaml
discussion_id: discuss-tags-on-project
round: 1
agent: claude-code
verdict: disagree
position: >
  Tags should be stored as a JSONB column on the projects table.
  This avoids a join table and keeps queries simple for our current scale.
points:
  - id: storage
    verdict: disagree
    rationale: "JSONB is simpler than a separate tags table for < 10k rows"
  - id: querying
    verdict: agree
    rationale: "Both approaches support GIN indexing"
submitted_at: "2026-03-15T10:00:00Z"
```

**Codex CLI writes `round-1-codex-cli.yaml`:**
```yaml
discussion_id: discuss-tags-on-project
round: 1
agent: codex-cli
verdict: disagree
position: >
  Tags should use a normalized join table (project_tags).
  This is more flexible for future filtering and reporting.
points:
  - id: storage
    verdict: disagree
    rationale: "Join table is standard relational practice"
  - id: querying
    verdict: agree
    rationale: "Both work, but join table is more portable across DBs"
submitted_at: "2026-03-15T10:05:00Z"
```

### Step 3 — Round 2: Agents Respond to Each Other

Each agent sees the other's position and either agrees, maintains their stance, or finds middle ground:

**Claude Code (round 2) — changes to `partial`:**
```yaml
verdict: partial
position: >
  Concede: join table is more portable. But for our current Postgres-only
  setup, JSONB avoids schema migrations. Propose: JSONB now, migrate to
  join table if we add a second DB backend.
```

**Codex CLI (round 2) — changes to `agree`:**
```yaml
verdict: agree
position: >
  The phased approach makes sense. JSONB for now with a documented
  migration path. Adding a note to decisions.yaml.
```

### Step 4 — Resolution

When both agents agree (or max rounds are reached), the discussion closes and a decision record is written:

```
shux discuss resolve --id discuss-tags-on-project
```

This creates an entry in `.superharness/decisions.yaml`:

```yaml
decisions:
  - id: tags-storage-model
    what: "Store tags as JSONB column on projects table"
    why: "Simpler for current scale, avoids unnecessary join table. Will migrate to normalized table if a second DB backend is added."
    alternatives: ["Normalized join table (project_tags)"]
    date: 2026-03-15
    by: claude-code, codex-cli
    status: accepted
    discussion: discuss-tags-on-project
```

### Step 5 — Verify in Status

```
shux status
```

Shows:
```
Discussions:
  discuss-tags-on-project  resolved  2 rounds  decision: tags-storage-model
```

## Discussion States

| State | Meaning |
|-------|---------|
| `open` | Waiting for agent positions |
| `active` | At least one round submitted, more rounds available |
| `resolved` | Both agents agreed or max rounds reached |
| `stale` | No activity for > 48 hours |

## Key Rules

1. Agents **must not act** on a disputed point until the discussion resolves
2. Each round is append-only — agents cannot edit previous rounds
3. The human owner can force-resolve at any time with `shux discuss resolve --force`
4. All positions and rationales are preserved in the discussion directory for audit
