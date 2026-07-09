---
description: Run any superharness (shux) CLI command and return its output
argument-hint: "<shux-subcommand> [args...]"
---

Run `shux $ARGUMENTS` via Bash in the current project directory. Print stdout/stderr verbatim — do not summarize or reformat unless asked. If `shux` is not on PATH, tell the user to check their pipx install or run `pip install -e .` for a repo-local dev venv.
