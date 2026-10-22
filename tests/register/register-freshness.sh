#!/usr/bin/env bash

# Register freshness gate.
#
# A register (docs/REGISTER-*.md, or docs/registers/REGISTER-*.md) is a dated
# snapshot: its header records the base commit, the date and the counts it read.
# This gate compares those recorded facts against the live tree and says whether
# the snapshot still describes it. It never writes the register.
#
# Run: bash tests/register/register-freshness.sh [--forge]
#   --forge also compares the open-issue count, which needs glab or gh.
#
# Exit 0: fresh. Exit 1: stale, after printing what drifted and the fixing
# command. Exit 2: cannot evaluate (no metadata line, unreadable header, forge
# requested but unavailable) -- never a pass, because a check that cannot
# measure must say so instead of implying freshness.
#
# No register in this repository is not a failure: exit 0 with a note. The
# scaffold ships none, and an inventory is opt-in.

set -euo pipefail

FORGE=0
[ "${1:-}" = "--forge" ] && FORGE=1

MAX_COMMITS="${REGISTER_MAX_COMMITS:-25}"
MAX_DAYS="${REGISTER_MAX_DAYS:-14}"
DOC_DRIFT="${REGISTER_DOC_DRIFT:-2}"
UNTRACKED_DRIFT="${REGISTER_UNTRACKED_DRIFT:-5}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  echo "register-freshness: not a git repository -- cannot evaluate" >&2
  exit 2
fi
cd "$REPO_ROOT"

# Newest register wins: filenames carry an ISO date, so a plain sort is enough.
REGISTER=""
for candidate in $(ls -1 docs/registers/REGISTER-*.md docs/REGISTER-*.md 2>/dev/null | sort -r); do
  REGISTER="$candidate"
  break
done

if [ -z "$REGISTER" ]; then
  echo "register-freshness: no register in this repository -- nothing to check"
  exit 0
fi

META="$(grep -m1 'register-freshness:' "$REGISTER" 2>/dev/null || true)"
if [ -z "$META" ]; then
  echo "register-freshness: $REGISTER has no 'register-freshness:' metadata line." >&2
  echo "  Add one so this gate can read the snapshot's base, date and counts:" >&2
  echo "  <!-- register-freshness: base=<rev> date=<YYYY-MM-DD> documents=<n> untracked=<n> issues=<n> -->" >&2
  echo "  Without it the register's freshness cannot be evaluated -- exit 2, not a pass." >&2
  exit 2
fi

# key=value pairs, read with sed so no JSON parser is needed here. No \b: BSD sed
# on macOS does not support word boundaries, and a gate that silently reads ""
# there would report every register as missing its base.
meta() {
    # Read the key=value pairs with bash itself: no sed expression to interpolate
    # the key into, so there is no delimiter to escape and no regex built from
    # caller input (shipguard SHELL-004). `read -ra` splits on whitespace without
    # globbing, which the unquoted form would do on a value holding a `*`.
    local pair
    read -ra pairs <<< "$META"
    for pair in "${pairs[@]}"; do
        case "$pair" in
            "$1="*) printf '%s\n' "${pair#*=}"; return 0 ;;
        esac
    done
}

BASE="$(meta base)"
R_DATE="$(meta date)"
R_DOCS="$(meta documents)"
R_UNTRACKED="$(meta untracked)"
R_ISSUES="$(meta issues)"

for pair in "base:$BASE" "date:$R_DATE" "documents:$R_DOCS" "untracked:$R_UNTRACKED"; do
  if [ -z "${pair#*:}" ]; then
    echo "register-freshness: $REGISTER metadata is missing '${pair%%:*}' -- cannot evaluate" >&2
    exit 2
  fi
done

echo "register-freshness: $REGISTER"
echo "  thresholds: ${MAX_COMMITS} commits, ${MAX_DAYS} days, ${DOC_DRIFT} documents, ${UNTRACKED_DRIFT} untracked files"

STALE=0
UNKNOWN=0
report() { printf '  %-22s recorded %-8s live %-8s %s\n' "$1" "$2" "$3" "$4"; }

# ── Base commit distance ──────────────────────────────────────────────────────
if BASE_SHA="$(git rev-parse --verify --quiet "${BASE}^{commit}" 2>/dev/null)"; then
  COMMITS="$(git rev-list --count "${BASE_SHA}..HEAD")"
  if [ "$COMMITS" -gt "$MAX_COMMITS" ]; then
    report "commits since base" "$BASE" "$COMMITS" "STALE (limit ${MAX_COMMITS})"
    STALE=1
  else
    report "commits since base" "$BASE" "$COMMITS" "ok"
  fi
else
  echo "  base commit            $BASE            UNKNOWN (not in this clone; fetch deeper history)"
  UNKNOWN=1
fi

# ── Date age (portable: GNU date, then BSD/macOS date) ────────────────────────
TODAY_EPOCH="$(date -u +%s)"
DATE_EPOCH=""
if date -u -d "$R_DATE" +%s >/dev/null 2>&1; then
  DATE_EPOCH="$(date -u -d "$R_DATE" +%s)"
elif date -u -j -f "%Y-%m-%d" "$R_DATE" +%s >/dev/null 2>&1; then
  DATE_EPOCH="$(date -u -j -f "%Y-%m-%d" "$R_DATE" +%s)"
fi
if [ -n "$DATE_EPOCH" ]; then
  AGE_DAYS=$(( (TODAY_EPOCH - DATE_EPOCH) / 86400 ))
  if [ "$AGE_DAYS" -gt "$MAX_DAYS" ]; then
    report "age (days)" "$R_DATE" "$AGE_DAYS" "STALE (limit ${MAX_DAYS})"
    STALE=1
  else
    report "age (days)" "$R_DATE" "$AGE_DAYS" "ok"
  fi
else
  echo "  age (days)             $R_DATE            UNKNOWN (no portable date arithmetic)"
  UNKNOWN=1
fi

# ── Document count drift ─────────────────────────────────────────────────────
LIVE_DOCS="$(git ls-files -- docs/ 2>/dev/null | grep -cE '/(BUG|AUDIT|REVIEW|DECISION|ARCH|PLAN|REGISTER|SPEC)-' || true)"
DOC_DELTA=$(( LIVE_DOCS - R_DOCS ))
[ "$DOC_DELTA" -lt 0 ] && DOC_DELTA=$(( -DOC_DELTA ))
if [ "$DOC_DELTA" -gt "$DOC_DRIFT" ]; then
  report "work documents" "$R_DOCS" "$LIVE_DOCS" "STALE (delta ${DOC_DELTA})"
  STALE=1
else
  report "work documents" "$R_DOCS" "$LIVE_DOCS" "ok"
fi

# ── Untracked file drift ─────────────────────────────────────────────────────
LIVE_UNTRACKED="$(git ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ')"
UNTRACKED_DELTA=$(( LIVE_UNTRACKED - R_UNTRACKED ))
[ "$UNTRACKED_DELTA" -lt 0 ] && UNTRACKED_DELTA=$(( -UNTRACKED_DELTA ))
if [ "$UNTRACKED_DELTA" -gt "$UNTRACKED_DRIFT" ]; then
  report "untracked files" "$R_UNTRACKED" "$LIVE_UNTRACKED" "STALE (delta ${UNTRACKED_DELTA})"
  STALE=1
else
  report "untracked files" "$R_UNTRACKED" "$LIVE_UNTRACKED" "ok"
fi

# ── Open issues (opt-in: needs a forge CLI) ──────────────────────────────────
if [ "$FORGE" = 1 ]; then
  if [ -z "$R_ISSUES" ]; then
    echo "  open issues            (none)           UNKNOWN (metadata has no 'issues' key)"
    UNKNOWN=1
  elif command -v glab >/dev/null 2>&1; then
    LIVE_ISSUES="$(glab issue list --state opened --per-page 100 2>/dev/null | grep -cE '^#' || true)"
    report "open issues" "$R_ISSUES" "$LIVE_ISSUES" "ok"
  elif command -v gh >/dev/null 2>&1; then
    LIVE_ISSUES="$(gh issue list --state open --limit 100 2>/dev/null | wc -l | tr -d ' ')"
    report "open issues" "$R_ISSUES" "$LIVE_ISSUES" "ok"
  else
    echo "  open issues            $R_ISSUES            UNKNOWN (--forge requested, no glab or gh)"
    UNKNOWN=1
  fi
fi

echo
if [ "$STALE" = 1 ]; then
  echo "  register STALE: refresh it from the live sources, then commit the refresh."
  echo "  /register <programme> --from-register $REGISTER"
  exit 1
fi
if [ "$UNKNOWN" = 1 ]; then
  echo "  register freshness PARTIALLY EVALUATED: some checks could not run (see UNKNOWN above)."
  exit 2
fi
echo "  register fresh."
exit 0

