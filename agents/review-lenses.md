# Review Lenses

Instead of one reviewer checking everything, split reviews into specialized lenses. Each lens focuses on one aspect. Can run in parallel.

---

## Why Lenses

One reviewer doing "check everything" produces shallow reviews. Nine specialized lenses running in parallel produce deeper, more actionable findings. This is how serious security audits work — different teams check different things.

---

## The Lenses

### 1. Security
**Focus:** Auth, access control, secrets, injection, data exposure.
**Checklist:**
- Are credentials hardcoded or in env vars?
- Input validation on all user-facing endpoints?
- SQL injection, XSS, CSRF protection?
- Auth checks on every protected route?
- Secrets in git history?
- Dependencies with known CVEs?

### 2. Architecture
**Focus:** Design patterns, coupling, dependency direction, modularity.
**Checklist:**
- Does this follow the existing architecture or fight it?
- Dependency direction correct (inner layers don't import outer)?
- New abstractions justified or premature?
- Module boundaries respected?
- Would a new team member understand this?

### 3. Performance
**Focus:** N+1 queries, unnecessary computation, memory leaks, scaling bottlenecks.
**Checklist:**
- Database queries optimized? Indexes used?
- Unnecessary loops or redundant computation?
- Memory allocation in hot paths?
- Caching opportunities missed?
- Will this break at 10x current load?

### 4. Tests
**Focus:** Coverage, edge cases, test quality, flaky tests.
**Checklist:**
- Happy path AND error paths tested?
- Edge cases covered (empty input, null, boundary values)?
- Tests are deterministic (no time/random dependencies)?
- Integration tests where needed?
- Tests actually assert the right things (not just "doesn't crash")?

### 5. Error Handling
**Focus:** Failure modes, graceful degradation, logging, user-facing errors.
**Checklist:**
- All external calls have try/catch or error handling?
- Errors logged with enough context to debug?
- User-facing errors are helpful, not stack traces?
- Partial failures handled gracefully?
- Retry logic where appropriate?

### 6. DevOps / Infra
**Focus:** Deployment, CI/CD, configuration, observability.
**Checklist:**
- Config via env vars, not hardcoded?
- Dockerfile/compose changes correct?
- CI pipeline still passes?
- Monitoring/alerting for new endpoints?
- Rollback plan if this breaks in production?

### 7. API Contract
**Focus:** Backwards compatibility, documentation, versioning.
**Checklist:**
- Breaking changes to existing APIs?
- Request/response types documented?
- API versioning respected?
- Error response format consistent?
- OpenAPI/Swagger updated?

---

## How to Use

### In a contract (per-task lens assignment)
```yaml
tasks:
  - id: auth-module
    assigned_to: codex-cli
    reviewer: claude-code
    review_lenses: [security, architecture, error-handling]
```

### As parallel subagents
Claude Code can spawn multiple review passes:
```
For each lens in review_lenses:
  → Spawn subagent with lens checklist as system prompt
  → Feed it the diff
  → Collect findings
  → Merge into single review handoff
```

### As sequential review
For simpler setups, the reviewer reads the relevant lens checklists before reviewing and addresses each one.

---

## Adding Custom Lenses

Add project-specific lenses in `.superharness/review-lenses/`:
```yaml
# .superharness/review-lenses/hipaa.yaml
name: HIPAA Compliance
focus: PHI handling, audit logs, encryption at rest, access controls
checklist:
  - Is PHI encrypted at rest and in transit?
  - Audit log for all PHI access?
  - Minimum necessary access principle followed?
  - BAA requirements met for third-party services?
```

Custom lenses merge with the default set.

---

## Rules

1. **Not every task needs all lenses.** Assign relevant lenses per task in the contract.
2. **Security lens is mandatory** for any task touching auth, user data, or external APIs.
3. **Findings go in the handoff**, not in the ledger. Ledger gets a one-line summary.
4. **Disagreements are valuable.** If two lenses conflict (performance vs security), log both perspectives.
