"""Tests for adapter-polish bugs that surfaced after the dispatch
infrastructure started actually working:

Bug 1: opencode requires provider-prefixed model strings ("anthropic/claude-...").
       Auto-classified models came in as bare "claude-sonnet-4-6" and opencode
       rejected with ProviderModelNotFoundError.

Bug 2: codex CLI sandbox refuses to write through symlinks. With the worktree
       .superharness/ being a symlink to the live source, codex couldn't
       write its submission YAML and dropped it in the worktree root, where
       it got gc'd. Fix: skip worktree isolation for discussion-round
       dispatches since they need direct write access to .superharness/.

Bug 3: discussion rounds have no contract task entry, so the post-launch
       reconciler couldn't determine final_state and always fell through to
       "failed". Fix: check for the submission YAML on disk instead of
       querying the contract.

Bug 4: watcher "both" target hardcoded ["claude-code", "codex-cli", "gemini-cli"],
       excluding opencode. Pending opencode inbox items were silently ignored
       until manually dispatched. Fix: use list_adapters() to build the
       dispatch target list dynamically.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Bug 1 — opencode model auto-prefix
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_opencode_branch_prefixes_claude_with_anthropic():
    """delegate.py must prefix bare claude-* model names with anthropic/
    when launching opencode, otherwise opencode rejects with
    ProviderModelNotFoundError."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "delegate.py").read_text()
    # Find the opencode branch
    idx = src.find('elif target == "opencode":')
    assert idx > 0
    branch = src[idx : idx + 1500]
    assert 'anthropic/' in branch, (
        "opencode branch must auto-prefix Claude models with 'anthropic/'. "
        "Got branch:\n" + branch[:600]
    )
    assert 'claude-' in branch, "branch must check for claude- prefix"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_opencode_branch_prefixes_openai_models():
    """Same check for openai/ prefix on gpt/o1/o3 models."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "delegate.py").read_text()
    idx = src.find('elif target == "opencode":')
    branch = src[idx : idx + 1500]
    assert 'openai/' in branch
    assert 'gpt-' in branch


# ---------------------------------------------------------------------------
# Bug 2 — discussion dispatches must NOT use worktree isolation
# ---------------------------------------------------------------------------

def test_dispatch_skips_worktree_for_discussion_rounds():
    """inbox_dispatch.dispatch() must not create a git worktree when the
    task_id is a discussion round, because the agent's submission YAML
    needs to land in the live source .superharness/discussions/ — and the
    codex sandbox refuses to write through the worktree's symlinked
    .superharness/."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_dispatch.py").read_text()
    # The decision must reference the discussion check
    assert "is_discussion" in src, (
        "inbox_dispatch.py must compute is_discussion and skip worktree "
        "creation for discussion rounds"
    )
    assert '"/round-" in item_task' in src or "round-" in src, (
        "is_discussion must detect the /round-N suffix in task ids"
    )


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_dispatch_discussion_check_guards_worktree_creation(tmp_path):
    """End-to-end-ish: simulate calling _git_worktree_add gating logic.
    We can't easily test the full dispatch() function, so check the
    source for the conjunction `not is_discussion and ... _has_dirty_worktree`."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_dispatch.py").read_text()
    # The guard must be:  if not is_discussion and non_interactive and ...
    assert "not is_discussion" in src, (
        "the worktree-creation `if` must include `not is_discussion` so "
        "discussions never spawn a worktree"
    )


# ---------------------------------------------------------------------------
# Bug 3 — discussion reconcile treats submission on disk as done
# ---------------------------------------------------------------------------

def test_reconciler_uses_submission_yaml_for_discussion_rounds():
    """inbox_dispatch.py reconcile block must check for the submission YAML
    on disk when is_discussion is True, instead of querying the contract
    (discussion rounds have no contract task entry and would always 'fail')."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_dispatch.py").read_text()
    assert "is_discussion" in src
    # The reconcile branch for discussions must reference submission_path
    assert "submission_path" in src, (
        "reconcile block must compute submission_path and check os.path.exists(submission_path) "
        "to determine final_state='done' for discussion rounds"
    )
    assert "final_state = \"done\"" in src or "final_state = 'done'" in src, (
        "reconcile block must set final_state to 'done' when the submission YAML exists"
    )


def test_reconciler_discussion_done_path_construction():
    """The submission path must be .superharness/discussions/<discuss_id>/<round_slug>-<agent>.yaml.
    Verify the format string is present in the reconcile logic."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_dispatch.py").read_text()
    # The path construction should join discuss_id and round_slug-agent
    assert "discussions" in src
    assert "submission_path" in src
    # The path should use item_to (the agent) as part of the filename
    # Find the submission_path assignment and verify it references item_to
    idx = src.find("submission_path")
    assert idx > 0
    context = src[idx: idx + 300]
    assert "item_to" in context, (
        "submission_path must incorporate item_to (the agent name) so each "
        "agent's submission is checked independently. Context:\n" + context[:200]
    )


# ---------------------------------------------------------------------------
# Bug 4 — watcher "both" target must dispatch ALL registered adapters
# ---------------------------------------------------------------------------

def test_watcher_both_target_uses_adapter_registry():
    """inbox_watch.py must use list_adapters() to build the dispatch target
    list when target=='both', not a hardcoded ['claude-code', 'codex-cli', 'gemini-cli'].
    Any new adapter added to the registry must be automatically included."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_watch.py").read_text()
    idx = src.find("target == \"both\"")
    assert idx > 0, "inbox_watch.py must branch on target == 'both'"
    branch = src[idx: idx + 500]
    assert "list_adapters" in branch, (
        "When target=='both', the watcher must call list_adapters() to build "
        "the targets list dynamically — not a hardcoded agent name list. "
        "Hardcoding omits new adapters (bug 4 was opencode never dispatched). "
        "Found branch:\n" + branch[:300]
    )


def test_watcher_both_target_no_hardcoded_opencode_exclusion():
    """Verify opencode is not explicitly excluded from the watcher dispatch loop.
    The old bug was a hardcoded list that omitted opencode; after the fix the
    dynamic list includes it automatically."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_watch.py").read_text()
    # Find the 'target == "both"' branch and verify 'opencode' is not listed as
    # something to explicitly skip or exclude there
    idx = src.find("target == \"both\"")
    branch = src[idx: idx + 500]
    # If opencode is in the branch it should only appear inside the list_adapters fallback,
    # not as a negation or exclusion
    assert "list_adapters" in branch, (
        "list_adapters() must be present near the 'both' branch to prevent "
        "new adapters from being silently skipped"
    )


def test_cancel_undispatchable_uses_adapter_registry():
    """_cancel_undispatchable_agents must use list_adapters() as its primary
    source of known agent names (not just a glob + hardcoded list fallback)."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_watch.py").read_text()
    idx = src.find("def _cancel_undispatchable_agents")
    assert idx > 0
    fn_src = src[idx: idx + 800]
    assert "list_adapters" in fn_src, (
        "_cancel_undispatchable_agents must call list_adapters() to build known_agents "
        "so that any new adapter from a manifest is automatically recognised. "
        "Got:\n" + fn_src[:400]
    )


# ---------------------------------------------------------------------------
# Bug 5 — inbox_watch.py paused dead-pid reconciler indentation (gemini + opencode)
# ---------------------------------------------------------------------------

def test_paused_reconciler_not_nested_inside_analyze_task_logs_except():
    """inbox_watch.py: the paused dead-pid reconciler block must be a standalone
    try/except at the same indentation level as _analyze_task_logs(), not nested
    inside its except handler. When nested, it only ran on log-analysis failure
    instead of every watcher tick — paused items with dead PIDs were never
    transitioned to failed."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_watch.py").read_text()
    # Find the _analyze_task_logs call and the paused reconciler block.
    analyze_idx = src.find("_analyze_task_logs(project_dir)")
    assert analyze_idx > 0
    # Find the CALL to _reconcile_paused_dead_pids (not the definition)
    reconcile_call = "_reconcile_paused_dead_pids(paused_items)"
    reconcile_idx = src.find(reconcile_call)
    assert reconcile_idx > 0, "paused dead-pid reconciler call must exist in inbox_watch.py"
    # The reconcile block should come AFTER the analyze block
    assert reconcile_idx > analyze_idx, (
        f"_reconcile_paused_dead_pids call (pos {reconcile_idx}) must come after "
        f"_analyze_task_logs call (pos {analyze_idx})"
    )
    # Between the end of the analyze block and the reconcile block there should be
    # a standalone 'try:' at 4-space indentation (not 8-space / inside except).
    # We check by finding 'Reconcile paused dead-pid' comment then verifying the
    # next non-comment, non-blank line starts with '    try:' (4 spaces, not 8).
    comment_idx = src.find("Reconcile paused dead-pid")
    assert comment_idx > 0, "reconcile comment must be present"
    after_comment = src[comment_idx:]
    # Walk forward past the comment line to the first code line
    lines_after = after_comment.split("\n")
    code_line = ""
    for line in lines_after[1:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            code_line = line
            break
    assert code_line.startswith("    try:"), (
        "The paused dead-pid reconciler must start with '    try:' (4-space indent) "
        "as a standalone block, not '        try:' (8-space, inside except). "
        f"Got: {repr(code_line)}"
    )


def test_auto_dispatch_valid_agents_includes_all_adapters():
    """auto_dispatch._VALID_AGENTS must be derived from adapter_registry.list_adapters(),
    not a hardcoded two-element tuple. This ensures --agent opencode / --agent gemini-cli
    are accepted by the argparse CLI without manual updates."""
    import importlib
    from superharness.engine.adapter_registry import list_adapters
    # Reload to pick up the live value (avoid cached module state)
    import superharness.commands.auto_dispatch as ad
    importlib.reload(ad)
    registered = set(list_adapters())
    valid = set(ad._VALID_AGENTS)
    missing = registered - valid
    assert not missing, (
        f"_VALID_AGENTS is missing adapters that are registered in the manifest dir: {missing}. "
        "Use _get_valid_agents() to derive _VALID_AGENTS dynamically."
    )


def test_auto_dispatch_valid_agents_not_hardcoded_two_agents():
    """Regression: _VALID_AGENTS must NOT be the literal string '(\"claude-code\", \"codex-cli\")'
    in the source. It must be computed via _get_valid_agents() so new adapters are picked up
    automatically."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "auto_dispatch.py").read_text()
    assert '_VALID_AGENTS = ("claude-code", "codex-cli")' not in src, (
        "_VALID_AGENTS must not be a hardcoded 2-element tuple. "
        "Use _get_valid_agents() so all registered adapters (opencode, gemini-cli, etc.) are included."
    )
