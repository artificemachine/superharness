#!/bin/bash
# worktree.sh — Manage git worktrees for parallel Claude sessions
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "ERROR: Not in a git repo" >&2; exit 1; }
REPO_NAME=$(basename "$REPO_ROOT")
PARENT_DIR=$(dirname "$REPO_ROOT")

_worktree_dir() {
  local branch="$1"
  local safe="${branch//\//-}"
  echo "$PARENT_DIR/${REPO_NAME}-${safe}"
}

_ancestor_comm() {
  # Walk up the process tree and print all ancestor comm names
  local pid=$$
  while [[ $pid -gt 1 ]]; do
    local comm ppid
    comm=$(ps -o comm= -p "$pid" 2>/dev/null || true)
    echo "$comm"
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ' || true)
    [[ -z "$ppid" || "$ppid" == "0" || "$ppid" == "$pid" ]] && break
    pid=$ppid
  done
}

_open_claude() {
  local dir="$1"
  local branch
  branch=$(basename "$dir")

  local ancestors
  ancestors=$(_ancestor_comm)

  if [[ -n "${TMUX:-}" ]] || echo "$ancestors" | grep -q "^tmux"; then
    tmux new-window -n "$branch" -c "$dir" "claude"
    echo "Opened new tmux window '$branch' in: $dir"
  elif [[ -n "${ZELLIJ_SESSION_NAME:-}" ]]; then
    # Pass $dir as positional arg to avoid injection if path contains single quotes
    zellij action new-tab --name "$branch" -- bash -c 'cd "$1" && claude' _ "$dir"
  elif echo "$ancestors" | grep -qi "cmux"; then
    # cmux (macOS terminal multiplexer) — no scriptable CLI; guide the user
    echo ""
    echo "  Open a new cmux pane/tab and run:"
    printf '    cd %q && claude\n' "$dir"
    echo ""
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    # Use AppleScript's quoted form of to safely handle paths with spaces/quotes
    osascript - "$dir" <<'APPLESCRIPT'
on run argv
  tell application "Terminal" to do script "cd " & quoted form of (item 1 of argv) & " && claude"
end run
APPLESCRIPT
  else
    echo "INFO: Open a new terminal and run: cd '$dir' && claude"
  fi
}

cmd="${1:-list}"
shift || true

case "$cmd" in

  enter)
    branch="${1:-}"
    [[ -z "$branch" ]] && { echo "Usage: worktree enter <branch-name>"; exit 1; }
    wt_dir=$(_worktree_dir "$branch")

    if [[ -d "$wt_dir" ]]; then
      echo "Worktree already exists at: $wt_dir"
    else
      if git show-ref --verify --quiet "refs/heads/$branch"; then
        git worktree add "$wt_dir" "$branch"
      else
        git worktree add -b "$branch" "$wt_dir"
        echo "Created new branch: $branch"
      fi
      echo "Worktree created at: $wt_dir"
    fi

    _open_claude "$wt_dir"
    echo "Claude opened in: $wt_dir"
    ;;

  exit)
    current=$(pwd -P)
    main_wt=$(git worktree list --porcelain | awk '/^worktree/{print $2; exit}')
    main_wt=$(cd "$main_wt" && pwd -P)

    if [[ "$current" == "$main_wt" ]]; then
      echo "ERROR: You are in the main worktree. Cannot remove it." >&2
      exit 1
    fi

    echo "Removing worktree: $current"
    git worktree remove "$current" 2>/dev/null || git worktree remove --force "$current"
    echo "Done. Main repo is at: $main_wt"
    ;;

  switch)
    branch="${1:-}"
    [[ -z "$branch" ]] && { echo "Usage: worktree switch <branch-name>"; exit 1; }
    wt_dir=$(_worktree_dir "$branch")

    if [[ ! -d "$wt_dir" ]]; then
      echo "ERROR: No worktree found for branch '$branch' at $wt_dir" >&2
      echo "Tip: run 'worktree enter $branch' to create it first."
      exit 1
    fi

    _open_claude "$wt_dir"
    echo "Switched to: $wt_dir"
    ;;

  cleanup)
    branch="${1:-}"
    if [[ -z "$branch" ]]; then
      echo "Usage: worktree cleanup <branch-name>"
      echo "       worktree cleanup --all"
      exit 1
    fi

    main_wt=$(git worktree list --porcelain | awk '/^worktree/{print $2; exit}')

    if [[ "$branch" == "--all" ]]; then
      removed=0
      while IFS= read -r wt; do
        [[ "$wt" == "$main_wt" ]] && continue
        echo "Removing: $wt"
        git worktree remove --force "$wt" 2>/dev/null && ((removed++)) || true
      done < <(git worktree list --porcelain | awk '/^worktree/{print $2}')
      git worktree prune
      echo "Removed $removed worktree(s)."
    else
      wt_dir=$(_worktree_dir "$branch")
      if [[ ! -d "$wt_dir" ]]; then
        echo "ERROR: No worktree found at $wt_dir" >&2
        exit 1
      fi
      git worktree remove "$wt_dir" 2>/dev/null || git worktree remove --force "$wt_dir"
      echo "Removed worktree: $wt_dir"
    fi
    ;;

  list)
    echo "Worktrees for repo: $REPO_NAME"
    echo ""
    git worktree list
    ;;

  help|--help|-h)
    cat <<'EOF'
worktree.sh — Manage git worktrees for parallel Claude sessions

USAGE:
  worktree.sh enter <branch>      Create worktree + open Claude in new terminal
  worktree.sh exit                Remove the current worktree (must be inside one)
  worktree.sh switch <branch>     Open Claude in an existing worktree
  worktree.sh cleanup <branch>    Remove a specific worktree by branch name
  worktree.sh cleanup --all       Remove all non-main worktrees
  worktree.sh list                List all active worktrees

NOTES:
  - Worktree dirs are created as siblings of the main repo:
      <parent>/<repo-name>-<branch-name>
  - Branches with slashes are sanitized: feature/foo → repo-feature-foo
  - On macOS, enter/switch open a new Terminal window with claude running.
  - On Linux, a manual cd path is printed instead.
EOF
    ;;

  *)
    echo "Unknown command: $cmd"
    echo "Run: worktree.sh help"
    exit 1
    ;;

esac
