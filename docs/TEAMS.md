# Using superharness in a Team

superharness works well for solo and team setups. This page covers the decisions that matter when more than one person (or more than one agent) shares a project.

---

## Should we commit `.superharness/` to git?

| Scenario | Recommendation |
|----------|----------------|
| Solo project, personal machine | Ignore — add `.superharness/` to `.gitignore` |
| Team project, shared state | Commit — gives everyone the same contract, ledger, and handoffs |
| Repo where agents will open PRs | Commit — agents read/write contract.yaml before each session |

Both options work. Ignoring keeps the repo clean. Committing enables any team member (or any agent) to pick up exactly where the last session left off.

**To commit:**
```bash
git add .superharness/
```

**To ignore:**
```bash
echo '.superharness/' >> .gitignore
```

---

## Who owns which tasks?

Tasks have an `owner` field (`claude-code` or `codex-cli`). On a team:

- Assign tasks by agent type, not by person — any team member can launch the owning agent.
- Use `superharness contract today --project .` to see current task assignments.
- Reassign with `superharness task status --project . --id <task> --status todo --actor <agent>`.

---

## Shared failure and decision memory

`.superharness/failures.yaml` and `.superharness/decisions.yaml` are cross-agent. All sessions — human-launched or background — read and write these files.

**Best practice:** Promote task-local failures to `failures.yaml` when they're reusable (i.e., the same mistake could happen again in a different task). Run `superharness hygiene --strict` to check alignment.

---

## Multiple agents running at the same time

superharness uses file-based locking (`inbox.yaml.lock.d/`) to serialize dispatch. Two watchers on the same project directory will not double-dispatch the same task.

**Avoid:** running two watchers pointed at the same `.superharness/` directory from different machines simultaneously — file locking is local, not network-aware. If you need multi-machine, commit state to git and pull before dispatching.

---

## CI integration

superharness runs on Linux in foreground mode. For CI:

```bash
SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES \
superharness watch --foreground --project . --interval 60 --launcher-timeout 300
```

Or use `dispatch` directly for a single-shot job:

```bash
superharness dispatch --project . --to claude-code
```

---

## Onboarding a new team member

1. Clone the project (or pull latest if `.superharness/` is committed).
2. Install superharness: `bash /path/to/superharness/scripts/install-wrapper.sh`
3. Run `superharness doctor --project .` to verify the setup.
4. Read the current contract: `superharness contract today --project .`

That's it — the contract and ledger are already there; no fresh init needed.

---

## Further reading

- [GUIDE.md](GUIDE.md) — Full command reference
- [ARCHITECTURE.md](ARCHITECTURE.md) — How the protocol works internally
- [SECURITY.md](../SECURITY.md) — Threat model for background watcher
