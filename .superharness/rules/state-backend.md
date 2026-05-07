---
id: state-backend
title: State lives in SQLite
status: active
since: v1.41
---

All project state lives in `.superharness/state.sqlite3`.

contract.yaml, inbox.yaml, failures.yaml, and decisions.yaml are DEAD.
Do not read them. Do not write them. Do not reference them in prompts.

For task data:   use `state_reader.get_tasks()` or `shux contract`
For inbox data:  use `state_reader.get_inbox_items()` or `shux status`
For failures:    use `failures_dao.get_recent()`
For decisions:   use `decisions_dao.get_recent()`

The only legitimate YAML files in `.superharness/` are:
  - profile.yaml (project config)
  - heartbeat.yaml / watcher.yaml (runtime)
  - agent-pulse.yaml (agent health)
  - onboarding.yaml (onboarding state)

Everything else is dead. If you see a reference to contract.yaml, inbox.yaml,
failures.yaml, or decisions.yaml in source code, it's a bug.
