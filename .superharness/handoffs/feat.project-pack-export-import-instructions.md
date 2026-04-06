Task: Project packs: export and import portable .superharness state (feat.project-pack-export-import)

## Acceptance Criteria
- Add shux pack export and shux pack import for portable project state
- Export scrubs secrets, machine-local watcher/install state, and unsafe absolute-path metadata
- Import handles collisions deterministically and preserves portable protocol files
- Round-trip export/import regression tests pass on representative sample projects
- Portable pack format is documented for operators and agents

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done