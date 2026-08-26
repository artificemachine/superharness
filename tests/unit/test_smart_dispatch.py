"""Tests for engine/smart_dispatch.py — Phase 4 smart agent routing."""

from __future__ import annotations

from pathlib import Path


def _make_manifest(manifests_dir: Path, name: str, tags: list[str]) -> None:
    manifests_dir.mkdir(parents=True, exist_ok=True)
    tags_str = ", ".join(f'"{t}"' for t in tags)
    content = (
        f"name: {name}\n"
        f'version: "1"\n'
        f'description: "{name} adapter"\n'
        f"tags: [{tags_str}]\n"
    )
    (manifests_dir / f"{name}.yaml").write_text(content)


def _stub_tier_classification(monkeypatch, tier: str = "standard") -> None:
    """Keep auto-dispatch tests deterministic and provider-free."""
    from superharness.engine import model_router

    monkeypatch.setattr(model_router, "classify_task", lambda *args, **kwargs: (tier, "medium"))


# ---------------------------------------------------------------------------
# No manifests — fallback to owner
# ---------------------------------------------------------------------------


def test_choose_agent_no_manifests_returns_owner(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent

    task = {"id": "t1", "title": "fix bug", "owner": "codex-cli"}
    result = choose_agent(task, manifests_dir=str(tmp_path / "nonexistent"))
    assert result == "codex-cli"


def test_choose_agent_no_manifests_no_owner_returns_fallback(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent

    task = {"id": "t1", "title": "fix bug"}
    result = choose_agent(task, manifests_dir=str(tmp_path / "nonexistent"))
    assert result == "claude-code"


# ---------------------------------------------------------------------------
# Skill match
# ---------------------------------------------------------------------------


def test_choose_agent_picks_best_match(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent

    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "claude-code", ["planning", "coding", "docs"])
    _make_manifest(mdir, "codex-cli", ["refactor", "coding"])

    task = {"id": "t1", "title": "write docs and plan", "owner": "codex-cli"}
    result = choose_agent(task, manifests_dir=str(mdir))
    assert result == "claude-code"


def test_choose_agent_returns_owner_when_no_match(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent

    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "claude-code", ["coding"])
    _make_manifest(mdir, "codex-cli", ["refactor"])

    task = {"id": "t1", "title": "quantum entanglement research", "owner": "gemini-cli"}
    result = choose_agent(task, manifests_dir=str(mdir))
    assert result == "gemini-cli"


def test_choose_agent_exact_tag_match(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent

    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "codex-cli", ["refactor"])
    _make_manifest(mdir, "claude-code", ["planning"])

    task = {"id": "t1", "title": "refactor the auth module", "owner": "claude-code"}
    result = choose_agent(task, manifests_dir=str(mdir))
    assert result == "codex-cli"


# ---------------------------------------------------------------------------
# Task keyword extraction
# ---------------------------------------------------------------------------


def test_task_keywords_from_tags_list(tmp_path):
    from superharness.engine.smart_dispatch import _task_keywords

    task = {"title": "implement feature", "tags": ["security", "auth"]}
    kw = _task_keywords(task)
    assert "security" in kw
    assert "auth" in kw
    assert "implement" in kw


def test_task_keywords_empty_task():
    from superharness.engine.smart_dispatch import _task_keywords

    assert _task_keywords({}) == set()


# ---------------------------------------------------------------------------
# Score function
# ---------------------------------------------------------------------------


def test_score_zero_when_no_overlap():
    from superharness.engine.smart_dispatch import _score

    manifest = {"name": "codex-cli", "tags": ["refactor", "test"]}
    assert _score(manifest, {"planning", "docs"}) == 0


def test_score_counts_matches():
    from superharness.engine.smart_dispatch import _score

    manifest = {"name": "claude-code", "tags": ["planning", "docs", "coding"]}
    assert _score(manifest, {"planning", "docs", "security"}) == 2


# ---------------------------------------------------------------------------
# Empty task (no keywords) — falls back to owner
# ---------------------------------------------------------------------------


def test_choose_agent_empty_task_returns_owner(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent

    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "claude-code", ["coding"])
    task = {"owner": "codex-cli"}
    result = choose_agent(task, manifests_dir=str(mdir))
    assert result == "codex-cli"


# ---------------------------------------------------------------------------
# Pi smart-dispatch guard (PLAN-pi-adapter.md iteration 10)
# ---------------------------------------------------------------------------


def test_explicit_agent_override_routes_pi(monkeypatch, capsys, tmp_path):
    """An explicit Pi request bypasses automatic smart-routing gates."""
    from superharness.commands import auto_dispatch
    from superharness.engine import state_reader

    task = {"id": "pi-fixture", "title": "fixture task", "status": "todo"}
    monkeypatch.setattr(auto_dispatch, "is_project_initialized", lambda project: True)
    monkeypatch.setattr(state_reader, "get_contract_doc", lambda project: {"tasks": [task]})
    monkeypatch.setattr(auto_dispatch, "_classify_task", lambda task, project: ("claude-code", "standard"))

    assert auto_dispatch.run_auto_dispatch(str(tmp_path), dry_run=True, agent_override="pi") == 0
    assert "queue pi-fixture  agent=pi  tier=standard" in capsys.readouterr().out


def test_auto_dispatch_unmatched_task_preserves_owner(monkeypatch, tmp_path):
    """No smart match retains the contract owner instead of a tier heuristic."""
    from superharness.commands.auto_dispatch import _classify_task

    _stub_tier_classification(monkeypatch)
    task = {
        "id": "owner-parity",
        "title": "unmatched quantum task",
        "owner": "gemini-cli",
    }

    assert _classify_task(task, str(tmp_path)) == ("gemini-cli", "standard")


def test_promoted_pi_is_smart_selected(monkeypatch, tmp_path):
    """The production consumer selects promoted Pi only for its exact strength."""
    from superharness.commands.auto_dispatch import _classify_task

    _stub_tier_classification(monkeypatch)
    task = {"id": "promoted-pi", "title": "AGENT:PI", "owner": "codex-cli"}

    assert _classify_task(task, str(tmp_path)) == ("pi", "standard")


def test_promoted_exact_match_retains_pi_owner(monkeypatch, tmp_path):
    """A promoted Pi owner remains Pi when its exact strength is requested."""
    from superharness.commands.auto_dispatch import _classify_task

    _stub_tier_classification(monkeypatch)
    task = {"id": "promoted-owner-pi", "title": "AGENT:PI", "owner": "pi"}

    assert _classify_task(task, str(tmp_path)) == ("pi", "standard")


def test_promoted_unmatched_pi_owner_is_preserved(monkeypatch, tmp_path):
    """No-match behavior preserves a promoted Pi owner like any other owner."""
    from superharness.commands.auto_dispatch import _classify_task

    _stub_tier_classification(monkeypatch)
    task = {"id": "unmatched-owner-pi", "title": "unmatched quantum task", "owner": "pi"}

    assert _classify_task(task, str(tmp_path)) == ("pi", "standard")


def test_pi_preview_matches_exact_agent_tag():
    """Preview scoring sees Pi only for the exact, case-normalized tag."""
    from superharness.engine.smart_dispatch import choose_agent

    task = {"id": "preview-pi", "title": "route AGENT:PI", "owner": "codex-cli"}

    assert choose_agent(task) == "pi"


def test_pi_preview_rejects_near_miss_agent_tags():
    """Colon-bearing tags are exact tokens, never substring matches."""
    from superharness.engine.smart_dispatch import choose_agent

    for title in ("route agent:pi-helper", "route agent:pine", "route pi"):
        assert choose_agent({"title": title, "owner": "codex-cli"}) == "codex-cli"


def test_choose_agent_preserves_manifest_tie_order(tmp_path):
    """Equal scores retain the existing sorted manifest fallback order."""
    from superharness.engine.smart_dispatch import choose_agent

    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "alpha", ["shared"])
    _make_manifest(mdir, "beta", ["shared"])

    assert choose_agent({"title": "shared", "owner": "codex-cli"}, manifests_dir=str(mdir)) == "alpha"


def test_choose_agent_skips_malformed_manifest(tmp_path):
    """A malformed unrelated manifest cannot crash smart routing."""
    from superharness.engine.smart_dispatch import choose_agent

    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "codex-cli", ["refactor"])
    (mdir / "broken.yaml").write_text("name: [unterminated")

    assert choose_agent({"title": "refactor", "owner": "claude-code"}, manifests_dir=str(mdir)) == "codex-cli"


def test_auto_dispatch_enqueue_remains_plan_only(monkeypatch, tmp_path):
    """Implementation todo tasks still enter the existing plan-only inbox gate."""
    from superharness.commands.auto_dispatch import _enqueue
    from superharness.engine import inbox_dao

    captured = {}
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(inbox_dao, "enqueue", lambda conn, **kwargs: captured.update(kwargs))

    assert _enqueue(str(tmp_path / "project"), "plan-gate", "pi") is True
    assert captured["target_agent"] == "pi"
    assert captured["plan_only"] is True


def test_auto_dispatch_real_sqlite_selects_pi_and_enqueues_plan(monkeypatch, tmp_path):
    """Production classification selects promoted Pi while retaining the plan gate."""
    from superharness.commands.auto_dispatch import run_auto_dispatch
    from superharness.engine import inbox_dao, tasks_dao
    from superharness.engine.db import get_connection, init_db
    from superharness.engine.tasks_dao import TaskRow

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(tmp_path / "state"))
    _stub_tier_classification(monkeypatch)

    conn = get_connection(str(project))
    try:
        init_db(conn)
        tasks_dao.upsert(
            conn,
            TaskRow(
                id="sqlite-pi-owner",
                title="AGENT:PI",
                owner="pi",
                status="todo",
                effort="medium",
                project_path=str(project),
                development_method="tdd",
                acceptance_criteria=[],
                test_types=[],
                out_of_scope=[],
                definition_of_done=[],
                context=None,
                tdd=None,
                version=1,
                created_at="2026-08-26T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert run_auto_dispatch(str(project), dry_run=False) == 0

    conn = get_connection(str(project))
    try:
        rows = inbox_dao.get_all(conn)
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0].target_agent == "pi"
    assert rows[0].status == "pending"
    assert rows[0].plan_only is True
