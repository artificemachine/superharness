# Invariants: superharness

An invariant is a property that must hold after every operation, stated so that a
test can falsify it. A rule nothing tests is doctrine, not an invariant, so every
row below binds to the test that guards it.

Row format, parsed by `tests/doctrine/doctrine-guard.sh`:

```
INV-<n>: <statement> [(baseline)] -> tests/<file>[::[<Class>::]<test_name>[[<param>]]]
```

The binding is `<!-- PLACEHOLDER -->` until the test exists. The guard tolerates a
placeholder while the project has no tracked source, and refuses one afterwards.
Rows tagged `(baseline)` ship with every project and are not the project's own work;
`stateful` projects must add at least one row of their own, numbered from `INV-4`.

This registry stays project-wide: baseline rows and cross-cutting invariants about
the whole project live here. Invariants scoped to one specification live in that
spec's file under `docs/specs/`, with `INV-*` identifiers that stay globally unique
across the project and the same binding format. Never duplicate a scoped row here.
The guard enforces scoped rows through `--check traceability`, with the same
placeholder tolerance and test-target resolution as this registry.

## Invariants

- [INV-1] Every error leaves a persistent trace, with an explanation when one is known, and no partial failure is ever reported as success. (baseline) -> tests/unit/test_task_failed_reason.py::test_failed_status_requires_reason
- [INV-2] Every confirmed bug, gap, invariant violation and persistent failure gets a written report in the repo and becomes a private issue on the project's tracker (GitLab, GitHub or OpenProject), deduplicated, labelled `AI-gen`. (baseline) -> tests/doctrine/test_failure_reporting.py::test_incident_template_has_tracker_section
- [INV-3] No secret ever reaches a log or an issue, and when the tracker is unreachable the report is written locally and the publication queued. (baseline) -> tests/unit/test_redact.py::TestRedaction::test_redact_multiple_secrets

Add this project's own invariants below, starting at `INV-4`: one line each, stating
what must hold about the data this project owns, bound to the test that proves it.
