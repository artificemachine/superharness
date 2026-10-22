# Specification: superharness

This file is the system index for this project's specifications. One row per
spec below; each specification lives beside it under `docs/specs/`.

## Problem
AI coding assistants (Claude Code, Codex CLI, Gemini CLI, OpenCode, Pi) that work
on the same project step on each other and lose their state between sessions.
superharness gives them one shared, durable contract so work can be delegated,
reviewed, handed off and resumed without a human relaying state by hand.

## Scope
Included: the SQLite-backed task contract, queue-based delegation, the task
lifecycle and its gates, handoff and ledger state, model resolution through
runtime bindings, and the `shux` CLI with its watcher and dashboard.

Excluded: any dependency on the external RMDI router (ADR-0002), and model
selection by any authority other than runtime bindings. The specifications that
exist cover three bounded contracts (foundation, task lifecycle, model
resolution). `docs/ANALYSIS-spec-decomposition.md` proposes about 15 in total, so
the remaining contracts are not yet specified.

## Constraints
- State lives in SQLite. YAML files are export-only and never read as authoritative input (REQ-001).
- `CHANGELOG.md` is append-only (REQ-002).
- No tracked file carries a maintainer home path or username (INV-101).
- An installed copy never depends on the source checkout for execution, configuration or data.
- Nothing merges to `main` without owner approval. A release is triggered by a `v*` tag, never by a merge alone.

## Failure Reporting
Fixed constraints, inherited by every spec in this project. They are not a
placeholder to fill in: they hold as written, and `INVARIANTS.md` binds each one
to a test.

- Every error leaves a persistent trace, with an explanation when one is known. No partial failure is ever reported as success.
- Every confirmed bug, gap, invariant violation and persistent failure gets a written report in the repo and becomes a private issue on the project's tracker (GitLab, GitHub or OpenProject), deduplicated, labelled `AI-gen`.
- No secret ever reaches a log or an issue. When the tracker is unreachable, write a local report and queue the publication.

## Acceptance
- `bash tests/doctrine/doctrine-guard.sh` exits 0.
- `pytest tests/ -q` passes.
- Every row in the Specifications list below resolves to an existing file under `docs/specs/`.
- Every `REQ-*` and `INV-*` row in an active spec is bound to a test that exists.

## Specifications

One row per specification: identifier, title, path, status. A row whose status
is `superseded` must also name its successor with `-> SPEC-<nnn>` so
traceability has no silent dead end. Every path resolves to an existing file
under `docs/specs/`.

- [SPEC-001] Project foundation contract (docs/specs/SPEC-001-project-foundation.md) status: draft
- [SPEC-004] Task lifecycle state machine and gates (docs/specs/SPEC-004-task-lifecycle.md) status: draft
- [SPEC-006] Model resolution (docs/specs/SPEC-006-model-resolution.md) status: draft
