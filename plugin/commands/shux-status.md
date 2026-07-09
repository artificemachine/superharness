---
description: Superharness health dashboard — contract, watcher, inbox summary
argument-hint: "[--fix|--check]"
---

Run `shux status $ARGUMENTS` via Bash. Report watcher health, pending tasks, and any flagged issues verbatim. If the watcher is not running, ask the user whether to start it with `shux operator start --port 8787` — do not start it automatically.
