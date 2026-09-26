# Why a TUI for superharness?

## The problem

Operators have to context-switch constantly to check on agents.
- Browser dashboard requires the server running and a separate tab
- `shux contract` / `shux status` gives a static snapshot — not live
- Approving a plan means editing YAML or running a `shux task status` command
- Discussion threads and handoffs are buried in files

## What the TUI fixes

### 1. Situational awareness without leaving the terminal
One `shux tui` opens a live board: all tasks, status, owner, last update.
See instantly if an agent stalled, succeeded, or needs review.
No browser, no separate command.

### 2. Faster approve / reject cycles
Right now: approve a plan = manually edit `contract.yaml` or run `shux task status`.
With TUI: navigate to the task, press a key. The window between agent-proposes
and agent-proceeds shrinks from minutes to seconds.

### 3. Discussion and handoff visibility inline
Agents write threads and handoffs to files you'd otherwise hunt for.
The TUI surfaces them next to the task they belong to.

## Browser dashboard vs TUI

| | Browser dashboard | TUI |
|--|---|---|
| Monitoring from a separate screen | Best | — |
| Interactive approval during active terminal work | — | Best |
| Requires server running | Yes | No |
| Real-time | Yes (websocket) | Yes (poll) |

The TUI targets the workflow where you're already deep in a terminal session
and don't want to break flow.
