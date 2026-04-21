# Headless Auto-Dispatch Strategy

To make Auto-Dispatch a native, first-class feature of the engine (so it works without Morpheme or any UI running), Superharness should implement the following three components:

## 1. The "Contract Watcher" in `shux watcher-worker`
Currently, the watcher-worker only watches the Inbox (`inbox.yaml`). It is reactive—it waits for someone to put a "ticket" in its box.
* **The Upgrade**: The worker should also watch the Contract (`contract.yaml`).
* **The Logic**: If the worker sees a task that is `todo` + `ai_driven` + unblocked, it should self-enqueue. It shouldn't wait for a human to push the button. This turns the worker into an Active Agent rather than a passive one.

## 2. A Dependency-Resolution Hook
The engine needs a "trigger" that fires whenever a task status changes.
* **The Scenario**: Task A (Parent) is marked `done`.
* **The Action**: Superharness should immediately scan for all tasks that were `blocked_by: Task A`. For every unblocked task, if it's `ai_driven`, it should be moved to the inbox automatically.
* **The Result**: This creates a "Cascading Dispatch" where the AI finishes one task and immediately moves to the next logical step in the graph.

## 3. Policy-Based Auto-Approval
In `ai_driven` mode, the biggest bottleneck is often the transition from `plan_proposed` to `plan_approved`.
* **The Feature**: Superharness should implement a `policy.yaml` or `project_settings` field for Auto-Approval Gates.
* **Example Config**:
```yaml
autonomy_policy:
  auto_dispatch: true        # Move from todo -> enqueue
  auto_approve_plans: true   # Move from plan_proposed -> plan_approved
  max_concurrent_tasks: 2    # Safety throttle
```
* **Headless Flow**: The AI proposes a plan, the engine sees `auto_approve_plans: true`, validates the plan format, and immediately re-enqueues the agent for implementation.

## 4. Safety Gates & Throttling (The "Kill Switch")
If the system is auto-dispatching, it needs a way to prevent "Infinite Loop" costs.
* **Native Throttling**: The engine should track "Actions per Hour" or "Total Session Cost." If the AI gets stuck in a failure loop, Superharness should automatically flip the task from `ai_driven` to `oversight` (requiring a human to step in).

---

### Summary of the "Headless" Future:
If Superharness implements these, the workflow becomes:
1. **Human**: Defines the graph in `contract.yaml`.
2. **Human**: Runs `shux worker --auto-drive`.
3. **AI**: Wakes up, sees unblocked tasks, plans them, approves them (if permitted), executes them, and resolves the entire graph until it hits a task marked `hands_on` or a blocker it can't solve.

Morpheme's role then shifts from being a "Remote Control" to a "Flight Recorder" where you simply watch the playback of the AI's autonomous journey.
