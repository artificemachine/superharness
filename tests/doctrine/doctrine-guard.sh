#!/usr/bin/env bash
# 

# Doctrine guard: enforces this project's doctrine invariants (see RULES.md).
# Run: bash tests/doctrine/doctrine-guard.sh
# Run strict: bash tests/doctrine/doctrine-guard.sh --strict
# Run one check: bash tests/doctrine/doctrine-guard.sh --check <name>  (see --help)
# Exit 0: no check failed. Exit 1: a check failed, or (with --strict) a check
#         could not reach a verdict. Exit 2: unknown argument.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

# ── Verdict bookkeeping ───────────────────────────────────────────────────────
# Every check resolves to exactly one of three states, counted per check:
#   pass        a verdict was reached, and it is clean
#   fail        a doctrine violation was found
#   unverified  the check could not reach a verdict (missing input, missing tool)
# Each check reads only its own counter (begin_check/fail/end_check below), so a
# failure in one check can no longer change what a later check reports.
PASSES=0
FAILURES=0
UNVERIFIED=0
FAILED_NAMES=""
UNVERIFIED_NAMES=""

# --strict turns an unverified check into a failure. Opt-in only: the pre-commit
# hook and CI call the guard with no argument and keep the tolerant default.
STRICT=0
CHECK_FILTER=""
_CHECK_NAMES="changelog forbidden paths visibility version spec invariants traceability binary"

_usage() {
  cat <<USAGE
usage: doctrine-guard.sh [--strict] [--check <name>] [--help]
  --strict        an unverified check fails the run
  --check <name>  run one check only; names: ${_CHECK_NAMES}
  --help          this text
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --strict) STRICT=1 ;;
    --help | -h)
      _usage
      exit 0
      ;;
    --check)
      if [ "$#" -lt 2 ]; then
        echo "doctrine guard: --check needs a name" >&2
        _usage >&2
        exit 2
      fi
      CHECK_FILTER="$2"
      shift
      case " $_CHECK_NAMES " in
        *" $CHECK_FILTER "*) ;;
        *)
          echo "doctrine guard: unknown check: $CHECK_FILTER" >&2
          _usage >&2
          exit 2
          ;;
      esac
      ;;
    *)
      echo "doctrine guard: unknown argument: $1 (usage: doctrine-guard.sh [--strict] [--check <name>] [--help])" >&2
      exit 2
      ;;
  esac
  shift
done

# True when no --check filter was given, or when the filter names this check.
_selected() { [ -z "$CHECK_FILTER" ] || [ "$CHECK_FILTER" = "$1" ]; }

# Doctrine files and the marker the spec-first checks look for.
_PLACEHOLDER='<!-- PLACEHOLDER -->'
_SPEC_REL="docs/SPEC.md"
_INVARIANTS_REL="INVARIANTS.md"

# git-grep exclude list, shared across checks
_GREP_EXCLUDES=(
  ':(exclude).doctrine-forbidden'
  ':(exclude)tests/doctrine/*'
)

# ── Helpers ───────────────────────────────────────────────────────────────────

# begin_check opens a check: it prints the header and resets that check's
# counters. Every begin_check is paired with one end_check in the run-all block
# at the bottom, which is where the check's single verdict is recorded.
begin_check() {
  _CHECK_LABEL="$1"
  _CHECK_VERDICT=""
  _CHECK_FAILURES=0
  echo
  echo "check: $1"
}

# fail records a violation for the check in progress. A check may call it any
# number of times; end_check still records exactly one verdict.
fail() {
  echo "  [✗] $1"
  _CHECK_FAILURES=$((_CHECK_FAILURES + 1))
  _CHECK_VERDICT=fail
}

# ok records a clean verdict, but never erases a violation already recorded for
# this check: an "everything matched" line must not print over a match.
ok() {
  echo "  [✓] $1"
  [ -n "$_CHECK_VERDICT" ] || _CHECK_VERDICT=pass
}

# unverified records a check that could not reach a verdict — a missing input, a
# missing tool, a release still pending. It is not a failure unless --strict.
unverified() {
  echo "  [!] $1"
  [ "$_CHECK_VERDICT" = fail ] || _CHECK_VERDICT=unverified
}

# end_check records the verdict of the check that just ran. A check that reached
# no verdict at all is reported as unverified, never as a success.
end_check() {
  case "$_CHECK_VERDICT" in
    pass)
      PASSES=$((PASSES + 1))
      ;;
    fail)
      FAILURES=$((FAILURES + 1))
      FAILED_NAMES="${FAILED_NAMES}${_CHECK_LABEL}"$'\n'
      ;;
    *)
      UNVERIFIED=$((UNVERIFIED + 1))
      if [ "$_CHECK_VERDICT" = unverified ]; then
        UNVERIFIED_NAMES="${UNVERIFIED_NAMES}${_CHECK_LABEL}"$'\n'
      else
        UNVERIFIED_NAMES="${UNVERIFIED_NAMES}${_CHECK_LABEL} (reached no verdict)"$'\n'
      fi
      ;;
  esac
}

# ── 1. CHANGELOG.md is append-only vs HEAD ────────────────────────────────────

check_changelog_append_only() {
  begin_check "CHANGELOG.md append-only"

  if ! git -C "$REPO_ROOT" rev-parse HEAD >/dev/null 2>&1; then
    unverified "no HEAD yet: append-only check skipped (first commit)"
    return
  fi

  local committed working committed_len working_len
  committed="$(git -C "$REPO_ROOT" show HEAD:CHANGELOG.md 2>/dev/null || true)"
  working="$(cat "$REPO_ROOT/CHANGELOG.md" 2>/dev/null || true)"

  if [ -z "$committed" ]; then
    unverified "HEAD CHANGELOG.md is empty: append-only check skipped"
    return
  fi

  # Both vars have trailing newlines stripped by command substitution.
  # The working file must start with exactly the committed content.
  committed_len="${#committed}"
  working_len="${#working}"

  if [ "$working_len" -lt "$committed_len" ]; then
    fail "CHANGELOG.md is shorter than HEAD version; content was removed"
    return
  fi

  local working_prefix="${working:0:$committed_len}"
  if [ "$working_prefix" = "$committed" ]; then
    ok "CHANGELOG.md is append-only"
  else
    fail "CHANGELOG.md is not append-only: existing committed lines were modified or removed"
  fi
}

# ── 2. No forbidden identifiers in tracked files ──────────────────────────────

check_forbidden_identifiers() {
  begin_check "no forbidden identifiers in tracked files"

  local forbidden_file="$REPO_ROOT/.doctrine-forbidden"

  if [ ! -f "$forbidden_file" ]; then
    unverified ".doctrine-forbidden not found: identifier check skipped"
    return
  fi

  local pattern_count=0
  while IFS= read -r line || [ -n "$line" ]; do
    # Skip blank lines and comments
    [[ -z "$line" || "$line" == \#* ]] && continue
    pattern_count=$((pattern_count + 1))

    # Validate the regex via grep's own exit code (2 = syntax error). Portable
    # across GNU/BSD grep, unlike sniffing stderr text; their error wording differs.
    local grep_rc
    echo "" | grep -E -e "$line" >/dev/null 2>&1 && grep_rc=0 || grep_rc=$?
    if [ "$grep_rc" -eq 2 ]; then
      fail "malformed regex in .doctrine-forbidden: $line"
      continue
    fi

    # git grep exits 1 for "no match" and >1 for an error: an error is not a clean
    # result, so it must never fall through to the pass line below.
    local hits git_grep_rc=0
    hits="$(git -C "$REPO_ROOT" grep -nE -e "$line" -- . \
      "${_GREP_EXCLUDES[@]}" \
      2>/dev/null)" || git_grep_rc=$?
    if [ "$git_grep_rc" -gt 1 ]; then
      unverified "git grep failed (exit $git_grep_rc) while checking pattern '$line': identifier check cannot reach a verdict"
      continue
    fi

    if [ -n "$hits" ]; then
      fail "forbidden identifier pattern '$line' matched in tracked files:"
      echo "$hits" | sed 's/^/      /'
    fi
  done < "$forbidden_file"

  if [ "$pattern_count" -eq 0 ]; then
    unverified ".doctrine-forbidden has no active patterns: identifier check skipped"
    return
  fi

  if [ "$_CHECK_FAILURES" -eq 0 ] && [ -z "$_CHECK_VERDICT" ]; then
    ok "no forbidden identifiers found ($pattern_count pattern(s) checked)"
  fi
}

# ── 3. Named doctrine paths resolve on disk ───────────────────────────────────

check_doctrine_paths() {
  begin_check "doctrine paths resolve on disk"

  local scaffold_level
  scaffold_level="$(grep -E '^Scaffold level: [0-4]$' "$REPO_ROOT/RULES.md" 2>/dev/null | sed -E 's/^Scaffold level: //' | head -1 || true)"
  scaffold_level="${scaffold_level:-4}"

  local required=(
    "SOUL.md"
    "CLAUDE.md"
    "AGENTS.md"
    "GEMINI.md"
    "RULES.md"
    "CHANGELOG.md"
    "README.md"
    "LICENSE"
    ".env.example"
    "tests/doctrine"
    "tests/doctrine/doctrine-guard.sh"
  )

  for path in "${required[@]}"; do
    if [ "$path" = ".env.example" ] && [ "$scaffold_level" -lt 2 ]; then
      continue
    fi
    if [ ! -e "$REPO_ROOT/$path" ]; then
      fail "required doctrine path missing: $path"
    fi
  done

  # A loader that exists but is empty, or points nowhere, loads no doctrine. The
  # scaffold's loaders name COMMON.md, which in turn names RULES.md.
  local loader loader_text
  for loader in CLAUDE.md AGENTS.md GEMINI.md; do
    [ -f "$REPO_ROOT/$loader" ] || continue
    loader_text="$(cat "$REPO_ROOT/$loader")"
    if [ -z "${loader_text//[[:space:]]/}" ]; then
      fail "loader file $loader is empty"
    elif ! grep -qE 'RULES\.md|COMMON\.md' "$REPO_ROOT/$loader"; then
      fail "loader file $loader does not point at RULES.md or COMMON.md"
    fi
  done

  if [ "$_CHECK_FAILURES" -eq 0 ]; then
    ok "all doctrine paths resolve on disk"
  fi
}

# ── 4. Repo visibility matches the private-by-default doctrine ───────────────

_visibility_github() {
  if ! command -v gh >/dev/null 2>&1; then
    unverified "gh CLI not installed: cannot verify GitHub remote visibility, verify manually"
    return
  fi

  # gh resolves the repository from its working directory, so run it from the repo.
  local is_private
  if ! is_private="$(cd "$REPO_ROOT" && gh repo view --json isPrivate -q .isPrivate 2>/dev/null)"; then
    unverified "gh repo view failed (not authenticated, or repo not found): verify manually"
    return
  fi

  if [ "$is_private" = "true" ]; then
    ok "GitHub remote is private"
  else
    fail "GitHub remote is PUBLIC: CLAUDE.md declares private-by-default; fix repo visibility or the doctrine before committing"
  fi
}

_visibility_gitlab_gs() {
  # A host name says nothing about reachability, and nothing here probes it.
  unverified "remote host name matches gitlab.gs but its visibility was not tested: CLAUDE.md declares private-by-default, verify manually"
}

_visibility_gitlab_com() {
  local remote_url="$1"
  if ! command -v curl >/dev/null 2>&1 || [ -z "${GITLAB_TOKEN:-}" ]; then
    unverified "gitlab.com remote found but no curl/GITLAB_TOKEN available: cannot verify visibility, verify manually"
    return
  fi

  local project_path visibility
  # Accept the URL with or without the .git suffix and a trailing slash.
  project_path="$(printf '%s\n' "$remote_url" | sed -E 's#^.*gitlab\.com[:/]+##; s#/+$##; s#\.git$##')"
  # The token goes to curl on stdin as a config line: argv is visible to `ps`.
  # The timeouts keep a pre-commit hook from hanging on an unreachable host.
  visibility="$( line='header = "PRIVATE-TOKEN: '; line+="$GITLAB_TOKEN"; line+='"'; printf '%s\n' "$line" \
    | curl -s --config - --connect-timeout 5 --max-time 15 \
      "https://gitlab.com/api/v4/projects/$(printf '%s' "$project_path" | sed 's#/#%2F#g')" \
    | grep -o '"visibility":"[a-z]*"' | cut -d'"' -f4 || true)"

  if [ "$visibility" = "private" ]; then
    ok "gitlab.com remote is private"
  elif [ -n "$visibility" ]; then
    fail "gitlab.com remote visibility is '$visibility', not private: CLAUDE.md declares private-by-default; fix repo visibility or the doctrine before committing"
  else
    unverified "could not determine gitlab.com remote visibility: verify manually"
  fi
}

check_repo_visibility() {
  begin_check "repo visibility matches private-by-default doctrine"

  # A repo that is public by design declares it with a non-empty .public-repo
  # marker holding the reason; the marker is reviewed like any tracked file.
  if [ -s "$REPO_ROOT/.public-repo" ]; then
    ok "repo declared public by design (.public-repo): visibility check skipped"
    return 0
  fi

  local remote_url
  remote_url="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"

  case "$remote_url" in
    "")
      unverified "no remote configured yet: visibility check skipped"
      ;;
    *github.com*) _visibility_github ;;
    *gitlab.gs*) _visibility_gitlab_gs ;;
    *gitlab.com*) _visibility_gitlab_com "$remote_url" ;;
    *)
      unverified "remote host not recognized (github.com/gitlab.com/gitlab.gs); cannot verify visibility automatically, verify manually: $remote_url"
      ;;
  esac
}

# ── 5. Manifest version vs git tags ───────────────────────────────────────────

_manifest_file() {
  # Detect the manifest, first hit wins: pyproject.toml, package.json, Cargo.toml.
  # Echoes the path, or nothing when the project declares no manifest at all.
  local name
  for name in pyproject.toml package.json Cargo.toml; do
    if [ -f "$REPO_ROOT/$name" ]; then
      echo "$REPO_ROOT/$name"
      return 0
    fi
  done
  return 0
}

_manifest_version() {
  # Echoes the plain MAJOR.MINOR.PATCH version the manifest declares. Echoes
  # nothing when there is no manifest, or when the manifest declares no such
  # version (a dynamic version, or a prerelease like 1.2.3-rc1). The caller
  # distinguishes those two cases via _manifest_file.
  local manifest_file line raw
  manifest_file="$(_manifest_file)"
  [ -n "$manifest_file" ] || return 0

  case "$(basename "$manifest_file")" in
    package.json) line="$(grep -m1 -E '^[[:space:]]*"version":' "$manifest_file" || true)" ;;
    *)            line="$(grep -m1 -E '^version = "' "$manifest_file" || true)" ;;
  esac
  [ -n "$line" ] || return 0

  raw="$(echo "$line" | sed -E 's/.*"([0-9]+\.[0-9]+\.[0-9]+)".*/\1/')"
  echo "$raw"
  return 0
}

check_version_tag_consistency() {
  begin_check "manifest version vs git tags"

  local manifest_file manifest
  manifest_file="$(_manifest_file)"
  manifest="$(_manifest_version)"

  if [ -z "$manifest_file" ]; then
    unverified "no manifest (pyproject.toml/package.json/Cargo.toml): version/tag check skipped"
    return 0
  fi

  if [ -z "$manifest" ] || ! [[ "$manifest" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    unverified "$(basename "$manifest_file") declares no plain MAJOR.MINOR.PATCH version (dynamic or prerelease): version/tag check skipped"
    return 0
  fi

  local tag_ver
  tag_ver="$(git -C "$REPO_ROOT" tag -l 'v*' | sed 's/^v//' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1 || true)"

  if [ -z "$tag_ver" ]; then
    unverified "no v* tags yet: version/tag check skipped"
    return 0
  fi

  local highest
  highest="$(printf '%s\n%s\n' "$manifest" "$tag_ver" | sort -V | tail -1)"

  if [ "$tag_ver" = "$manifest" ]; then
    ok "manifest $manifest matches newest tag v$tag_ver"
  elif [ "$highest" = "$manifest" ]; then
    unverified "manifest $manifest is ahead of newest tag v$tag_ver: release pending"
  else
    fail "tag v$tag_ver is ahead of manifest $manifest: bump the manifest or remove the stray tag"
  fi
}

# .doctrine-source-paths declares implementation that no source extension gives
# away (deploy.yml, main.tf, a config-only project): one git pathspec per line,
# blank lines and # comments ignored.
_declared_source_paths() {
  local file="$REPO_ROOT/.doctrine-source-paths" line
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    printf '%s\n' "$line"
  done < "$file"
}

_tracked_source_files() {
  local declared=() line
  while IFS= read -r line; do
    declared+=("$line")
  done < <(_declared_source_paths)

  git -C "$REPO_ROOT" ls-files -- \
    '*.py' '*.pyi' '*.js' '*.jsx' '*.mjs' '*.cjs' '*.ts' '*.tsx' '*.rs' '*.go' '*.sh' \
    '*.java' '*.c' '*.cc' '*.cpp' '*.cxx' '*.h' '*.hpp' '*.rb' '*.php' '*.kt' '*.kts' \
    '*.swift' '*.vue' '*.svelte' \
    ${declared[@]+"${declared[@]}"} \
    "${_GREP_EXCLUDES[@]}" \
    ':(exclude)tests/**' ':(exclude)docs/**' ':(exclude)scripts/ci/**'
}

# "No source yet" is only a verdict when the project declared what source means.
# Without a declaration an empty extension match cannot tell a real scaffold from
# a project whose implementation is YAML, Terraform or JSON.
_no_source_verdict() {
  local phase="$1"
  if [ -n "$(_declared_source_paths)" ]; then
    ok "$phase: no source yet (nothing matches the paths in .doctrine-source-paths)"
  else
    unverified "$phase: no source found by extension and no .doctrine-source-paths declared, cannot tell whether an implementation exists"
  fi
}

# An instruction sentence the template puts above each marker. Deleting the marker
# leaves it behind, so it is never counted as content the author wrote.
_SPEC_TEMPLATE_SENTENCES=(
  "Describe the user problem this change solves."
  "State what this change includes and excludes."
  "Record technical, operational, security, and delivery constraints."
  "List the observable conditions that prove the work is complete."
)
_SPEC_FILL_SECTIONS=(Problem Scope Constraints Acceptance)

# Prints one line per unresolved part of the spec: a marker still present, or a
# section to be filled in that carries nothing beyond the template sentence.
_spec_unresolved_reasons() {
  local spec_file="$1" line section="" has_body=0 reported=0 name sentence is_template

  _spec_flush_section() {
    if [ "$reported" -eq 0 ] && [ "$has_body" -eq 0 ] && [ -n "$section" ]; then
      for name in "${_SPEC_FILL_SECTIONS[@]}"; do
        [ "$name" = "$section" ] && echo "section '$section' has no content beyond the template sentence"
      done
    fi
  }

  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" == "## "* ]]; then
      _spec_flush_section
      section="${line#\#\# }"
      has_body=0
      reported=0
      continue
    fi
    [[ -z "${line//[[:space:]]/}" ]] && continue
    if [ "$line" = "$_PLACEHOLDER" ]; then
      echo "placeholder marker still present${section:+ in section '$section'}"
      reported=1
      continue
    fi
    is_template=0
    for sentence in "${_SPEC_TEMPLATE_SENTENCES[@]}"; do
      [ "$line" = "$sentence" ] && is_template=1
    done
    [ "$is_template" -eq 1 ] || has_body=1
  done < "$spec_file"
  _spec_flush_section
}

check_spec_placeholders() {
  begin_check "SPEC.md placeholders"

  local spec_file="$REPO_ROOT/$_SPEC_REL"
  if [ ! -f "$spec_file" ]; then
    unverified "no SPEC.md: spec check skipped"
    return 0
  fi

  if [ -z "$(_spec_unresolved_reasons "$spec_file")" ]; then
    ok "spec is resolved"
    return 0
  fi

  local source_files
  source_files="$(_tracked_source_files)"

  if [ -z "$source_files" ]; then
    _no_source_verdict "spec-first"
    return 0
  fi

  fail "$_SPEC_REL has unresolved placeholder while tracked source files exist"
  _spec_unresolved_reasons "$spec_file" | sed 's/^/      /'
}

# Resolves a `tests/<file>[::[<Class>::]<node>[[<param>]]]` binding against the
# repository: the file must exist and every named segment must be found in it.
# Records one fail per missing target, named after the binding's owner, so the
# registry and the scoped spec V&V rows cannot drift apart.
_binding_target_resolves() {
  local owner_id="$1" binding="$2" test_file
  test_file="${binding%%::*}"
  if [ ! -f "$REPO_ROOT/$test_file" ]; then
    fail "$owner_id names missing test file: $test_file"
    return 0
  fi

  if [[ "$binding" == *"::"* ]]; then
    # tests/f.py::[Class::]test_name[[param]]: every named segment must exist in
    # the file. A parametrize id is a runtime suffix, so it is not searched for.
    local node="${binding#*::}" segment
    node="${node%%\[*}"
    local -a segments
    IFS=: read -r -a segments <<< "${node//::/:}"
    local last=$(( ${#segments[@]} - 1 )) idx=0
    for segment in "${segments[@]}"; do
      if [ "$idx" -lt "$last" ]; then
        grep -qE "class[ ]+$segment\\b" "$REPO_ROOT/$test_file" || fail "$owner_id names missing test class: $segment"
      else
        grep -qE "(def|fn|func|it|test)[ (]+['\"]?$segment\\b" "$REPO_ROOT/$test_file" || fail "$owner_id names missing test function: $segment"
      fi
      idx=$((idx + 1))
    done
  fi
}

check_invariants_bound() {
  begin_check "INVARIANTS.md bindings"

  local inv_file="$REPO_ROOT/$_INVARIANTS_REL"
  if [ ! -f "$inv_file" ]; then
    unverified "no INVARIANTS.md: invariants check skipped"
    return 0
  fi

  local source_files line binding inv_id invariant_count=0
  source_files="$(_tracked_source_files)"

  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" == "- [INV-"* ]] || continue
    invariant_count=$((invariant_count + 1))

    if ! printf '%s\n' "$line" | grep -Eq '^- \[INV-[0-9]+\] .+ -> (<!-- PLACEHOLDER -->|tests/[^: []+(::[A-Za-z_][A-Za-z0-9_]*)*(\[[^] ]*\])?)$'; then
      fail "malformed invariant line: $line"
      continue
    fi

    inv_id="$(printf '%s\n' "$line" | sed -E 's/^- \[(INV-[0-9]+)\].*/\1/')"
    binding="${line##* -> }"
    if [ "$binding" = "$_PLACEHOLDER" ]; then
      if [ -n "$source_files" ]; then
        fail "$inv_id still bound to a placeholder while tracked source files exist"
      fi
      continue
    fi

    _binding_target_resolves "$inv_id" "$binding"
  done < "$inv_file"

  if [ "$invariant_count" -eq 0 ]; then
    fail "INVARIANTS.md lists no invariant"
  elif [ "$_CHECK_FAILURES" -eq 0 ]; then
    if [ -z "$source_files" ]; then
      _no_source_verdict "invariants-first"
    else
      ok "invariants are bound"
    fi
  fi
}

# ── 5b. Spec index and status integrity ──────────────────────────────────────

# The multi-spec contract (docs/SPEC.md index + docs/specs/SPEC-*.md) is
# opt-in: a project opts in with its first "- [SPEC-" index row or by shipping
# a docs/specs/ directory. Projects without either are not judged here.
_traceability_opted_in() {
  grep -q '^- \[SPEC-' "$REPO_ROOT/docs/SPEC.md" 2>/dev/null && return 0
  [ -d "$REPO_ROOT/docs/specs" ]
}

# Prints "id|path|status|successor" for a well-formed index row; returns 1 for
# a line that opens like an index row but does not parse (the caller decides
# whether that is an unknown status or a malformed row) and for non-row lines.
_spec_index_row_fields() {
  local line="$1"
  [[ "$line" == "- [SPEC-"* ]] || return 1
  printf '%s\n' "$line" \
    | grep -E '^- \[SPEC-[0-9]+\] .+ \(docs/specs/[^)]+\.md\) status: (draft|approved|superseded)( -> SPEC-[0-9]+)?$' >/dev/null || return 1
  printf '%s\n' "$line" \
    | sed -E 's#^- \[(SPEC-[0-9]+)\] .+\((docs/specs/[^)]+\.md)\) status: (draft|approved|superseded)( -> SPEC-[0-9]+)?$#\1|\2|\3|\4#'
}

check_traceability() {
  begin_check "spec index and status integrity"

  local spec_index="$REPO_ROOT/docs/SPEC.md"
  if [ ! -f "$spec_index" ]; then
    unverified "no SPEC.md: traceability check skipped"
    return 0
  fi

  if ! _traceability_opted_in; then
    ok "multi-spec traceability not opted in (no index rows, no docs/specs/)"
    return 0
  fi

  local source_files line fields id path status successor all_ids=""
  local row_count=0 draft_unresolved=0 _status_word sid successors_rows=""
  local active_rows="" all_req_ids="" all_inv_ids=""
  source_files="$(_tracked_source_files)"

  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" == "- [SPEC-"* ]] || continue
    row_count=$((row_count + 1))

    if ! fields="$(_spec_index_row_fields "$line")"; then
      _status_word="$(printf '%s\n' "$line" | sed -E 's#^.* status: ([A-Za-z-]+).*$#\1#')"
      case "$_status_word" in
        draft|approved|superseded)
          fail "malformed spec index row: $line"
          ;;
        *)
          fail "unknown spec status '$_status_word' in index row: $line"
          ;;
      esac
      continue
    fi

    IFS='|' read -r id path status successor <<< "$fields"

    case "$status" in
      draft|approved) active_rows+="${id}|${path}|${status}"$'\n' ;;
    esac

    if printf '%s' "$all_ids" | grep -qx "$id"; then
      fail "duplicate spec id in index: $id"
      continue
    fi
    all_ids="${all_ids}${id}"$'\n'

    if [ ! -f "$REPO_ROOT/$path" ]; then
      fail "$id names missing spec file: $path"
      continue
    fi

    case "$status" in
      approved)
        if grep -qF -- "$_PLACEHOLDER" "$REPO_ROOT/$path"; then
          fail "approved spec still contains placeholder markers: $id"
        fi
        ;;
      draft)
        if grep -qF -- "$_PLACEHOLDER" "$REPO_ROOT/$path"; then
          draft_unresolved=1
        fi
        ;;
      superseded)
        if [ -z "$successor" ]; then
          fail "$id is superseded but names no successor (-> SPEC-nnn): traceability would end in a dead end"
        else
          successors_rows+="${successor# -> }"$'\n'
        fi
        ;;
    esac
  done < "$spec_index"

  if [ "$row_count" -eq 0 ]; then
    fail "docs/specs/ exists but docs/SPEC.md lists no specification index rows"
  fi

  for sid in $(printf '%s' "$successors_rows" | grep -x '.*' || true); do
    if ! printf '%s' "$all_ids" | grep -qx "$sid"; then
      fail "index names a successor that is not an index row: $sid"
    fi
  done

  if [ "$draft_unresolved" -eq 1 ]; then
    if [ -n "$source_files" ]; then
      fail "draft spec keeps placeholder rows while tracked source files exist"
    else
      _no_source_verdict "traceability-first"
    fi
  fi

  # ── Active-spec sweep: V&V bindings, scoped invariants, review freshness ──
  # Active specs (draft|approved) bind every REQ-*/INV-* row to a V&V target
  # that resolves, carry review metadata, and stay reviewed after the last
  # change to each declared tracked path. Superseded specs are excluded: their
  # index rows already name a successor. Placeholder bindings stay tolerated
  # only while no tracked source exists, the same rule as the registry.
  local active_row spec_file spec_line reviewed affected declared_reqs=""
  local declared_invs="" seen_vv="" rid rbinding vv_line need_id declared_path
  local last_commit affected_list
  while IFS= read -r active_row || [ -n "$active_row" ]; do
    [ -n "$active_row" ] || continue
    IFS='|' read -r id path status <<< "$active_row"
    spec_file="$REPO_ROOT/$path"
    declared_reqs=""
    declared_invs=""
    seen_vv=""
    if [ ! -f "$spec_file" ]; then
      continue # already reported as a missing spec file above
    fi

    reviewed="$(grep '^Last reviewed: ' "$spec_file" | head -1)"
    reviewed="${reviewed#Last reviewed: }"
    if [ -z "$reviewed" ] || ! printf '%s' "$reviewed" | grep -Eqx '[0-9]{4}-[0-9]{2}-[0-9]{2}'; then
      fail "$id is missing a well-formed 'Last reviewed: YYYY-MM-DD' metadata line"
      reviewed=""
    fi
    affected="$(grep '^Affected paths: ' "$spec_file" | head -1)"
    affected="${affected#Affected paths: }"
    if [ -z "$affected" ]; then
      fail "$id is missing the 'Affected paths:' metadata line"
    fi

    while IFS= read -r spec_line || [ -n "$spec_line" ]; do
      case "$spec_line" in
        "- [REQ-"*)
          rid="$(printf '%s\n' "$spec_line" | sed -E 's/^- \[(REQ-[0-9]+)\].*/\1/')"
          if printf '%s' "$all_req_ids" | grep -qx "$rid"; then
            fail "duplicate requirement id across active specs: $rid"
          else
            all_req_ids="${all_req_ids}${rid}"$'\n'
          fi
          declared_reqs="${declared_reqs}${rid}"$'\n'
          ;;
        "- [INV-"*)
          rid="$(printf '%s\n' "$spec_line" | sed -E 's/^- \[(INV-[0-9]+)\].*/\1/')"
          if printf '%s' "$all_inv_ids" | grep -qx "$rid"; then
            fail "duplicate scoped invariant id across active specs: $rid"
          else
            all_inv_ids="${all_inv_ids}${rid}"$'\n'
          fi
          declared_invs="${declared_invs}${rid}"$'\n'
          ;;
        "- REQ-"*|"- INV-"*)
          vv_line="$spec_line"
          if ! printf '%s\n' "$vv_line" | grep -Eq '^- (REQ|INV)-[0-9]+ -> (<!-- PLACEHOLDER -->|tests/[^: []+(::[A-Za-z_][A-Za-z0-9_]*)*(\[[^] ]*\])?)$'; then
            fail "malformed V&V binding row: $vv_line"
            continue
          fi
          rid="$(printf '%s\n' "$vv_line" | sed -E 's/^- ((REQ|INV)-[0-9]+) -> .*/\1/')"
          seen_vv="${seen_vv}${rid}"$'\n'
          rbinding="${vv_line#* -> }"
          if [ "$rbinding" = "$_PLACEHOLDER" ]; then
            if [ -n "$source_files" ]; then
              fail "$rid still bound to a placeholder while tracked source files exist"
            fi
            continue
          fi
          _binding_target_resolves "$rid" "$rbinding"
          ;;
      esac
    done < "$spec_file"

    for need_id in $declared_reqs $declared_invs; do
      if ! printf '%s' "$seen_vv" | grep -qx "$need_id"; then
        if [ "$status" = approved ] || [ -n "$source_files" ]; then
          fail "$need_id has no V&V binding row"
        fi
      fi
    done

    if [ -n "$reviewed" ] && [ -n "$affected" ] && [ "$affected" != "none" ]; then
      affected_list="${affected//, /$'\n'}"
      while IFS= read -r declared_path || [ -n "$declared_path" ]; do
        [ -n "$declared_path" ] || continue
        if git -C "$REPO_ROOT" ls-files --error-unmatch -- "$declared_path" >/dev/null 2>&1; then
          last_commit="$(git -C "$REPO_ROOT" log -1 --format=%cs -- "$declared_path" || true)"
          if [ -z "$last_commit" ]; then
            unverified "$id: no Git history for declared path $declared_path, review freshness unknown"
          elif [[ "$last_commit" > "$reviewed" ]]; then
            fail "$id review ($reviewed) predates last change to declared path $declared_path ($last_commit)"
          fi
        else
          unverified "$id declares untracked path $declared_path, review freshness unknown"
        fi
      done <<< "$affected_list"
    fi
  done <<< "$active_rows"

  if [ "$_CHECK_FAILURES" -eq 0 ] && [ -z "$_CHECK_VERDICT" ]; then
    ok "spec index and statuses are consistent ($row_count row(s))"
  fi
}

_project_slug() {
  local slug
  slug="$(basename "$REPO_ROOT")"

  [ -n "$slug" ] || return 1
  if [[ "$slug" == *$'\n'* || "$slug" == *$'\r'* || "$slug" == *"'"* || "$slug" == *'"'* ]]; then
    return 2
  fi

  printf '%s\n' "$slug"
  return 0
}


check_test_binary_resolution() {
  begin_check "same-line Python test binary resolution"

  local project_slug slug_status=0 test_files slug_pattern pattern hits
  test_files="$(git -C "$REPO_ROOT" ls-files -- \
    ':(glob)tests/*.py' ':(glob)tests/**/*.py' "${_GREP_EXCLUDES[@]}")"

  if [ -z "$test_files" ]; then
    unverified "no Python test suite: binary check skipped"
    return 0
  fi

  project_slug="$(_project_slug)" || slug_status=$?
  if [ "$slug_status" -eq 1 ]; then
    unverified "binary check skipped: could not derive project slug from repository root"
    return 0
  fi
  if [ "$slug_status" -eq 2 ]; then
    unverified "binary check skipped: cannot safely represent project slug containing quotes or newlines"
    return 0
  fi

  slug_pattern="$(printf '%s' "$project_slug" | sed 's/[][\\.^$*+?{}|()]/\\&/g')"
  pattern="subprocess\\.(run|call|check_call|check_output|Popen)[[:space:]]*\\([[:space:]]*\\[[[:space:]]*['\"]${slug_pattern}['\"]"
  hits="$(git -C "$REPO_ROOT" grep -nE "$pattern" -- \
    ':(glob)tests/*.py' ':(glob)tests/**/*.py' "${_GREP_EXCLUDES[@]}" 2>/dev/null || true)"

  if [ -n "$hits" ]; then
    fail "test resolves the project binary from PATH; use sys.executable -m <package> instead"
    echo "$hits" | sed 's/^/      /'
    return 0
  fi

  ok "Python test binary resolution is ready for $project_slug"
}

# ── Run all checks ─────────────────────────────────────────────────────────────

echo
echo "doctrine guard: $(basename "$REPO_ROOT")"
echo "────────────────────────────────────────"

_selected changelog && { check_changelog_append_only; end_check; }
_selected forbidden && { check_forbidden_identifiers; end_check; }
_selected paths && { check_doctrine_paths; end_check; }
_selected visibility && { check_repo_visibility; end_check; }
_selected version && { check_version_tag_consistency; end_check; }
_selected spec && { check_spec_placeholders; end_check; }
_selected invariants && { check_invariants_bound; end_check; }
_selected traceability && { check_traceability; end_check; }
_selected binary && { check_test_binary_resolution; end_check; }

echo
echo "────────────────────────────────────────"
if [ "$FAILURES" -gt 0 ]; then
  echo "  [✗] doctrine FAILED: $PASSES passed, $FAILURES failed, $UNVERIFIED unverified"
elif [ "$STRICT" -eq 1 ] && [ "$UNVERIFIED" -gt 0 ]; then
  echo "  [✗] doctrine FAILED (--strict): $PASSES passed, $FAILURES failed, $UNVERIFIED unverified"
elif [ "$UNVERIFIED" -gt 0 ]; then
  echo "  [!] doctrine OK with unverified checks: $PASSES passed, $FAILURES failed, $UNVERIFIED unverified"
else
  echo "  [✓] doctrine OK: $PASSES passed, $FAILURES failed, $UNVERIFIED unverified"
fi

if [ -n "$FAILED_NAMES" ]; then
  printf '%s' "$FAILED_NAMES" | sed 's/^/      failed: /'
fi
if [ -n "$UNVERIFIED_NAMES" ]; then
  printf '%s' "$UNVERIFIED_NAMES" | sed 's/^/      unverified: /'
fi

if [ "$FAILURES" -gt 0 ] || { [ "$STRICT" -eq 1 ] && [ "$UNVERIFIED" -gt 0 ]; }; then
  exit 1
fi
exit 0
# 
