# Concept: Agent-Owned Tools & Meta-Development
**Date:** 2026-04-21
**Core Idea:** The agent acts as its own library maintainer, mutating its toolset mid-task to overcome obstacles.

## 1. The Meta-Developer Philosophy
In a traditional automation stack, the agent is a **consumer** of tools. If a tool is missing or broken, the agent fails.
In the **Superharness + Browser-Harness** model, the agent is a **meta-developer**. It owns the lifecycle of its own capabilities:
1.  **Detection:** Identifying that an existing tool (e.g., `click_submit`) is failing due to a UI change.
2.  **Mutation:** Rewriting the logic in `helpers.py` to use a new selector or a different interaction pattern.
3.  **Validation:** Verifying the new tool works within the current task context.
4.  **Persistence:** Saving the new logic as a "Domain Skill" for future reuse.

## 2. Anatomy of a "Mutation"
When an agent "owns" its tools, it can fix "brittleness" autonomously.

**Example: A Broken CSS Selector**
*   **Initial Helper:** `def submit_form(): page.click("#old-id")`
*   **The Failure:** The website updates; `#old-id` is removed.
*   **The Healing:** The agent analyzes the page source, identifies the new class `.new-submit-btn`, and rewrites the helper:
    ```python
    def submit_form():
        # Healed on 2026-04-21: old ID removed by site update
        page.click(".new-submit-btn")
    ```

## 3. The Governance Loop
To prevent an agent from "healing" itself into a security vulnerability or inefficient code, Superharness provides a governance layer:
*   **Audit Trail:** Every mutation is recorded in the `ledger.md`.
*   **Task State:** Tool updates are treated as `plan_proposed` or `report_ready` transitions, requiring human or "Senior Agent" review.
*   **Rollback:** If a mutation is flawed, Superharness can use the git-backed state to revert `helpers.py` to a known-good version.

## 4. Notification Strategies
Because agents can now "self-write" code, real-time monitoring is essential.

### A. Dashboard Activity Feed
The `shux dashboard` provides a live timeline of every dispatch, mutation, and verification event. This is the primary way to observe "healing" patterns as they happen.

### B. Desktop Notifications
Running `shux notify-desktop` in the background will trigger native system toasts whenever an agent transitions a task status or completes a tool mutation.

### C. Remote Supervision (Telegram/Discord)
For mobile monitoring, the messaging gateway can be configured to alert you whenever a "Mutation" event is recorded in the ledger. This allows you to approve or deny a "self-healed" tool from your phone.

---

> **Advice:**
> Start with the `shux dashboard` to see the events in real-time. Once you are comfortable with the agent's "healing" patterns, we can set up the Telegram hook so you can supervise the agent's "self-writing code" from your phone.
