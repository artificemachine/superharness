# Claims vs Reality — superharness

**Date:** 2026-08-05
**Scope:** Public README and active documentation claims

## Claims audited

| Claim | Source | Verdict | Evidence |
|---|---|---|---|
| SQLite is the sole runtime source of truth | `README.md:341` | VERIFIED | `engine/db.py` initializes the SQLite schema/migrations; `utils/paths.py:136-178` chooses the active DB; `cli.py:158` exports YAML separately. |
| Normal pytest runs are offline | `README.md:236`, `CONTRIBUTING.md:9-17` | VERIFIED | `tests/conftest.py:31-52` sets deterministic router/summarizer guards and inert CLI stubs unless the explicit live-test env var is set. Security rerun observed only the inert stub, never a provider client. |
| 5,000+ tests protect the project | `README.md:51,425` | VERIFIED | Fresh clone collected 5,837 tests; the security rerun executed 5,252 passing tests, 584 skipped, and 2 expected failures. |
| `shux state` exposes dump/schema/shell/info operations | `docs/CONCEPT-notifications-and-state-isolation.md:455-489` | VIOLATED | `src/superharness/cli.py:140-165` registers no `state` command. Implemented alternatives include `backup-state`, `archive-yaml`, and `export-yaml`. |
| The architecture is consistently SQLite/XDG-based | `docs/ARCHITECTURE.md:29` | VIOLATED | The same document describes YAML engine operations at lines 42-48 and a YAML-era diagram/state model from line 72, contradicting the current resolver and SQLite runtime. |
| The tool is cross-platform | `README.md:325-335` | UNCHECKABLE | Workflows define Ubuntu, macOS, and Windows matrices, but this audit did not independently run each hosted runner. |

## Honesty score

**3 / 5 checkable public completion claims verified.** The runtime design is stronger than its supporting documentation; the current public docs overstate unavailable commands and mix two state architectures.

## Drift-class findings

- **Doc drift:** the concept document presents an unimplemented state-management CLI as current functionality.
- **Doc drift:** the architecture document retains YAML-era explanations after its SQLite migration banner.
- **Guard gap:** the new offline test guard is verified by behavior tests, but no contract test yet asserts that every agent CLI is intercepted. The full security rerun supplied runtime evidence.

## Remediation

- Mark concept-only `shux state`/advanced-backup content as a proposal, or align it with the shipped commands.
- Replace the architecture diagram and layer/state sections with the active SQLite/XDG architecture.
- Add a contract-level subprocess guard if future provider-cli call sites proliferate.
