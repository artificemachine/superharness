# ADR-0002: No RMDI router dependency; runtime bindings remain the model authority

## Status
Accepted (2026-09-24).

## Context
In July 2026, four commits on a side branch connected `shux delegate` to the
external RMDI router (`:8200`). Under `routing_strategy: rmdi`, model choice
moved from superharness to the router's seat bindings, a new `shux recipe`
command switched delegation recipes behind a consent gate, and the
orchestrator's decomposition and subtask fan-out ran through the router. A
review pass then made RMDI the default and native resolution an opt-out.

That work was never merged. Since then:

- PR #147 made runtime bindings the single production authority for model
  selection (dispatch, fallback, subtasks, orchestrator).
- The operator canon limits RMDI to projects whose goal or bootstrap requires
  a seat, a receipt or a recipe; otherwise no router is used.
- The branch forks from before the repository history rewrite and sits more
  than 700 commits behind `main`.

The branches were deleted on 2026-09-24. Their content is kept only as the
annotated tags `archive/rmdi-routing-2026-07` and
`archive/codex-hook-schema-2026-07`.

## Decision
superharness does not depend on the RMDI router. The archived RMDI routing
work is not merged, cherry-picked or ported. Model selection stays with
runtime bindings, with adapter manifests as the compatibility fallback.

The archive tags are a record of a rejected design, not pending work.

## Consequences
- One model authority: no `routing_strategy` setting, no `shux recipe`
  command, no RMDI client in the package, and no router availability
  requirement for dispatch.
- No seat or `bindingVersion` receipts are recorded by superharness; projects
  that need them use RMDI directly, outside superharness.
- The one unrelated fix in `archive/codex-hook-schema-2026-07`, commit
  `6378ce94` ("support Codex wire schema"), may be ported on its own, starting
  from `main`, without any RMDI code.
- Revisiting this decision requires a new ADR that supersedes this one.
