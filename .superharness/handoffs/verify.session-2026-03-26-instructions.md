Task: Verify: bug fixes, feat.task-dependencies, tdd block (verify.session-2026-03-26)

## Acceptance Criteria
- shux close rejects non-owner actors but allows actor=owner
- shux monitor --foreground prints error when server crashes, not silent
- shux hygiene passes without OBSIDIAN vault present (no error on missing vault)
- shux doctor shows PASS/WARN/INFO for enabled modules
- available_modules() returns non-empty list (module_templates in package)
- shux delegate refuses on status=todo and plan_proposed
- shux delegate refuses when blocked_by task is not done
- shux close refuses when status is not report_ready or review_passed
- shux close --force bypasses status gate
- shux task create --tdd-red/green/refactor writes tdd block to contract
- shux run --timeout works on macOS (no SIGALRM dependency)
- README shows v1.1.1, AGENTS.md shows Python only

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done