# SPEC-001: Project foundation contract

Status: draft
Last reviewed: 2026-10-25
Affected paths: CHANGELOG.md, src/superharness/scripts/check-changelog-append-only.sh

The starter spec holds the project-wide contract every later specification
builds on. Promotion to `approved` is the owner's act, never the guard's or an
agent's.

## Requirements

One row per requirement; the identifier is globally unique across every spec
in this project.

- [REQ-001] SQLite is the source of truth for state: no file outside the recorded baseline reads state YAML as authoritative input.
- [REQ-002] `CHANGELOG.md` is append-only: the checker rejects any edit or removal of an existing line.

## Scoped Invariants

One row per invariant scoped to this spec, using the same binding format as
`INVARIANTS.md`. Identifiers stay globally unique project-wide.

- [INV-101] No tracked file contains a maintainer home path or username.

## Known gaps

- The state YAML check behind REQ-001 tolerates the files listed in the test's baseline; it blocks new state YAML reads but does not prove the baseline is empty.

## Verification & Validation

One row per requirement and scoped invariant, bound to the test that proves
it: `tests/<file>[::<test>]`.

- REQ-001 -> tests/test_no_state_yaml_reads.py::test_no_new_state_yaml_reads
- REQ-002 -> tests/unit/test_changelog_append_only.py::test_append_only_fails_on_edit
- INV-101 -> tests/unit/test_no_tracked_personal_data.py::test_no_home_paths_in_tracked_files
