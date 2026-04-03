Task: Verify monitor UI: done tasks hidden by default, verify button tweak (v1.3.1) (verify.monitor-ui-done-hidden)

## Acceptance Criteria
- Tasks with status=done are hidden by default in the tasks panel (not rendered)
- Clicking the "done" pill badge toggles visibility of done tasks
- verify.* tasks in report_ready state show "Close Without Review" as primary button
- verify.* tasks in report_ready state show "Request Review" as a smaller secondary button
- Non-verify tasks in report_ready still show "Request Review" as primary action

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done