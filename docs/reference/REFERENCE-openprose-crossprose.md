# OpenProse Documentation Ownership

OpenProse, Reactor, and CrossProse migration documentation is owned by the companion `crossprose` repository, not Superharness.

Canonical location: the `docs/` directory in [newblacc/crossprose](https://github.com/newblacc/crossprose/tree/main/docs).

Start with:

- `ANALYSIS-crossprose-openprose-drift.md`
- `ANALYSIS-crossprose-migration-options.md`
- `GUIDE-openprose-standing-responsibilities.md`
- `GUIDE-what-is-reactor.md`

Do not infer a Superharness integration from those documents. Any future integration must be requested and designed separately.

Superharness-specific adaptation decisions, the conditions for treating the
combined system as spec-driven development, and the bounded proof-of-concept
decision and evidence gates are all recorded in
[`CONCEPT-openprose-reactor.md`](docs/concepts/CONCEPT-openprose-reactor.md) — Parts 1, 3 and 2
respectively.
