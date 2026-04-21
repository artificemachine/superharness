# Failure Management Strategy

To ensure autonomous operations are reliable and visible, we are implementing a three-layer failure management system.

## Layer 1: Proactive Visibility (Future)
*   **Goal**: Notify the operator immediately when a task requires human intervention.
*   **Mechanism**: Implement a `shux notify` command.
*   **Triggers**: 
    *   Task reaching max retry limit.
    *   Watcher crash.
    *   Critical budget threshold reached.
*   **Channels**: macOS/Linux desktop notifications, Telegram bot, or Slack webhook.

## Layer 2: Explicit Status Signaling (Active)
*   **Goal**: Remove ambiguity from `shux status`.
*   **Change**: Update the summary line to include the specific Task IDs that are failing.
*   **Status**: Implementing in `v1.29.3`.

## Layer 3: Failure Self-Healing (Active)
*   **Goal**: Give retrying agents enough context to fix environmental issues (like dirty worktrees).
*   **Change**: Inject system health context (`shux doctor` summary) into the prompt when `prior_failures` are detected.
*   **Status**: Implementing in `v1.29.3`.
