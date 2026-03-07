# Ship Pipeline — Layer 5

Security-first quality gates + architectural guardrails. Every commit passes through this.

---

## The Pipeline

```
1. Security scan       → grep for secrets, tokens, credentials
2. Rules verify        → CLAUDE.md/AGENTS.md rules still respected
3. Branch check        → not on main/master
4. Pre-commit hooks    → linters, formatters, path checks
5. Tests               → run full test suite
6. Build               → verify it compiles/bundles
7. Cross-agent review  → different agent reviews the diff
8. Hygiene             → no debug prints, no TODO hacks, no commented code
9. Commit              → never --no-verify, never --force
```

**Rule: security scan is always step 1. Non-negotiable.**

---

## Security Gates

### Secrets Detection
Before any commit:
- `grep -rn` for API keys, tokens, passwords, private keys
- Check .env files are in .gitignore
- Verify no credentials in CLAUDE.md, AGENTS.md, or state files
- Check for hardcoded paths (pre-commit hook blocks home-dir-relative references)

### Protected Files
Never edit without explicit permission:
- CLAUDE.md (global) — the harness core
- .env, .env.local — secrets
- credentials.json, tokens — auth
- Pre-commit hooks — quality enforcement

---

## Architectural Guardrails

(Inspired by OpenAI's Codex pattern: 1M lines, ~1,500 PRs, 3 engineers)

### Dependency Direction
Define which layers can import from which:

```
Types → Config → Repository → Service → Runtime → UI

Lower layers NEVER import from higher layers.
A Service can use a Repository. A Repository cannot use a Service.
```

Enforce this with:
- Import linting rules in the project's CLAUDE.md
- Structural tests that fail if boundaries are crossed
- Agent instructions: "Before adding an import, verify it flows downward"

### Module Boundaries
Each module has a public API. Agents should:
- Use the public API, not reach into internals
- Ask before creating cross-module dependencies
- Prefer composition over inheritance
- New functionality goes in the correct module, not wherever is convenient

### Drift Prevention
Without guardrails, each agent session introduces architectural drift:
- Functions end up in the wrong module
- Circular dependencies appear
- Convention inconsistencies accumulate
- Tech debt compounds silently

The fix: include architectural rules in per-project CLAUDE.md:
```markdown
## Architecture
- modules/auth/ handles all authentication. Nothing else touches auth logic.
- modules/api/ defines public endpoints. Business logic lives in modules/core/.
- No circular imports. If A imports B, B cannot import A.
```

---

## Cross-Agent Review Protocol

The agent that wrote the code is worst at reviewing it.

### When to Cross-Review
- Before merging any feature branch
- After Codex batch generation (Claude Code reviews)
- After Claude Code refactoring (Codex reviews)
- Before shipping to production (always)

### Review Checklist
The reviewing agent checks:
1. Does it do what was intended? (correctness)
2. Are there edge cases the author missed? (robustness)
3. Does it respect architectural boundaries? (structure)
4. Are there security concerns? (safety)
5. Is the code readable to a human? (maintainability)

### Review Format
```markdown
## Review: [feature/branch name]
**Reviewer:** [agent]
**Author:** [agent]

### Findings
- [severity: critical/warning/note] [file:line] [description]

### Verdict
[APPROVE / REQUEST_CHANGES / BLOCK]
```

---

## Rules

1. **Never `--no-verify`.** If hooks fail, fix the issue. Don't bypass.
2. **Never push to main.** Feature branches → PR → review → merge.
3. **Security scan before everything.** Not after tests, not after build. First.
4. **Cross-review before merge.** At minimum, a different agent reviews the diff.
5. **Architectural rules in CLAUDE.md.** If the rules aren't written, agents can't follow them.
