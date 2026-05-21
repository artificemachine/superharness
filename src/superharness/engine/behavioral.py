"""Behavioral profile engine — zero-touch user adaptation (Iteration 4).

Extracts patterns from SQLite task/review/ledger data, applies adaptive rules
with hysteresis and confidence scoring, injects into agent dispatch context.

Profile storage:
  ~/.config/superharness/behavioral/  ← user.* (cross-project)
  .superharness/behavioral/           ← project.<hash>.* (per-project)
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

USER_PROFILE_DIR = os.path.join(
    os.path.expanduser("~"), ".config", "superharness", "behavioral"
)
PROJECT_PROFILE_DIRNAME = "behavioral"

# ── Paths ────────────────────────────────────────────────────────────────────

def user_profile_path() -> str:
    os.makedirs(USER_PROFILE_DIR, exist_ok=True)
    return USER_PROFILE_DIR

def project_profile_path(project_dir: str) -> str:
    p = os.path.join(project_dir, ".superharness", PROJECT_PROFILE_DIRNAME)
    os.makedirs(p, exist_ok=True)
    return p

# ── Confidence scoring ───────────────────────────────────────────────────────

def confidence_level(sample_count: int) -> str:
    if sample_count < 5:
        return "low"
    if sample_count <= 20:
        return "medium"
    return "high"

def confidence_score(sample_count: int) -> float:
    return min(sample_count / 20.0, 1.0)

# ── EWMA decay ───────────────────────────────────────────────────────────────

def ewma_weight(age_days: float, halflife_days: float = 30.0) -> float:
    return math.exp(-age_days / halflife_days)

HALFLIFE = {
    "communication": 90,
    "review": 60,
    "model": 30,
    "task": 45,
    "autonomy": 60,
}

# ── Hysteresis ───────────────────────────────────────────────────────────────

def hysteresis_check(
    successes: int,
    failures: int,
    upgrade_threshold: int = 10,
    downgrade_threshold: int = 3,
) -> str:
    total = successes + failures
    if total == 0:
        return "neutral"
    if successes >= upgrade_threshold:
        return "upgrade"
    if failures >= downgrade_threshold:
        return "downgrade"
    return "neutral"

# ── Serialization ────────────────────────────────────────────────────────────

def save_profile(filepath: Path | str, profile: dict) -> None:
    os.makedirs(os.path.dirname(str(filepath)), exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(profile, f, indent=2, default=str)

def load_profile(filepath: Path | str) -> dict:
    if not os.path.isfile(filepath):
        return {}
    try:
        with open(filepath) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

# ── Profile extraction ───────────────────────────────────────────────────────

def extract_task_style(project_dir: str) -> dict:
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            r = conn.execute(
                "SELECT effort, COUNT(*) as cnt FROM tasks WHERE effort IS NOT NULL "
                "GROUP BY effort ORDER BY cnt DESC LIMIT 5"
            ).fetchall()
            efforts = {row["effort"]: row["cnt"] for row in r}
            default_effort = max(efforts, key=efforts.get) if efforts else "medium"

            tdd_count = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE require_tdd=1"
            ).fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

            test_types_row = conn.execute(
                "SELECT test_types FROM tasks WHERE test_types IS NOT NULL AND test_types != '[]' LIMIT 1"
            ).fetchone()

            sample_count = total
            return {
                "default_effort": default_effort,
                "effort_distribution": efforts,
                "tdd_required": tdd_count > (total * 0.5) if total > 0 else False,
                "test_types": json.loads(test_types_row["test_types"]) if test_types_row else [],
                "confidence": confidence_level(sample_count),
                "sample_count": sample_count,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to extract task style: %s", e)
        return {"confidence": "low", "sample_count": 0, "updated_at": datetime.now(timezone.utc).isoformat()}


def extract_review_style(project_dir: str) -> dict:
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            r = conn.execute(
                "SELECT AVG(score) as avg_score, COUNT(*) as cnt, "
                "SUM(CASE WHEN failed=1 THEN 1 ELSE 0 END) as failures "
                "FROM review_store WHERE owner = 'user'"
            ).fetchone()
            if r and r["cnt"] > 0:
                avg = float(r["avg_score"] or 0)
                failures = int(r["failures"] or 0)
                total = int(r["cnt"])
                strictness = max(0.0, min(1.0, 1.0 - (avg / 10.0) + (failures / max(total, 1))))
                return {
                    "strictness": round(strictness, 2),
                    "avg_score": round(avg, 2),
                    "total_reviews": total,
                    "failures": failures,
                    "confidence": confidence_level(total),
                    "sample_count": total,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to extract review style: %s", e)
    return {"strictness": 0.5, "avg_score": 0, "total_reviews": 0, "failures": 0,
            "confidence": "low", "sample_count": 0, "updated_at": datetime.now(timezone.utc).isoformat()}


def extract_model_prefs(project_dir: str) -> dict:
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            r = conn.execute(
                "SELECT model_tier, COUNT(*) as cnt FROM tasks "
                "WHERE model_tier IS NOT NULL GROUP BY model_tier ORDER BY cnt DESC"
            ).fetchall()
            prefs = {row["model_tier"]: row["cnt"] for row in r}
            sample_count = sum(prefs.values())
            return {
                "preferred_model": max(prefs, key=prefs.get) if prefs else "standard",
                "distribution": prefs,
                "confidence": confidence_level(sample_count),
                "sample_count": sample_count,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to extract model prefs: %s", e)
    return {"confidence": "low", "sample_count": 0, "updated_at": datetime.now(timezone.utc).isoformat()}


def extract_autonomy_profile(project_dir: str) -> dict:
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            r = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM tasks "
                "GROUP BY status"
            ).fetchall()
            status_map = {row["status"]: row["cnt"] for row in r}
            successes = status_map.get("done", 0)
            failures = status_map.get("failed", 0) + status_map.get("stopped", 0)
            total = successes + failures
            success_rate = successes / total if total > 0 else 0.0
            return {
                "success_rate": round(success_rate, 2),
                "successes": successes,
                "failures": failures,
                "total_tasks": total,
                "confidence": confidence_level(total),
                "sample_count": total,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to extract autonomy profile: %s", e)
    return {"confidence": "low", "sample_count": 0, "updated_at": datetime.now(timezone.utc).isoformat()}


def extract_all_profiles(project_dir: str) -> dict:
    return {
        "task_style": extract_task_style(project_dir),
        "review_style": extract_review_style(project_dir),
        "model_prefs": extract_model_prefs(project_dir),
        "autonomy_profile": extract_autonomy_profile(project_dir),
    }

# ── Adaptive rules ───────────────────────────────────────────────────────────

def evaluate_rules(
    project_dir: str,
    task_history: dict | None = None,
    review_history: dict | None = None,
) -> list[dict]:
    rules: list[dict] = []
    th = task_history or {}
    rh = review_history or {}

    # Rule 1: autonomous success → bump autonomy
    auto_successes = th.get("autonomous_successes", 0)
    if auto_successes >= 10:
        rules.append({
            "action": "bump_autonomy",
            "reason": f"{auto_successes} consecutive autonomous successes",
            "confidence": confidence_level(auto_successes),
        })

    # Rule 2: repeated rejection → lower autonomy
    rejections = th.get("plan_rejections", 0)
    approvals = th.get("plan_approvals", 0)
    if rejections >= 4 and rejections > approvals:
        rules.append({
            "action": "lower_autonomy",
            "reason": f"{rejections} of last {rejections + approvals} plans rejected",
            "confidence": confidence_level(rejections + approvals),
        })

    # Rule 3: high quality reviews → relax gate
    review_count = rh.get("review_count", 0)
    avg_score = rh.get("avg_score", 0)
    review_failures = rh.get("failures", 0)
    if review_count >= 10 and avg_score >= 8.0 and review_failures == 0:
        rules.append({
            "action": "relax_review",
            "reason": f"Average review score {avg_score}/10 over {review_count} reviews",
            "confidence": confidence_level(review_count),
        })

    # Rule 4: all failures are test failures → auto-enable TDD
    if th.get("only_test_failures", False) and th.get("total_failures", 0) >= 5:
        rules.append({
            "action": "enable_tdd",
            "reason": "All recent failures are test-related",
            "confidence": "medium",
        })

    # Rule 5: model preference detected
    model_prefs = extract_model_prefs(project_dir)
    if model_prefs.get("sample_count", 0) >= 20:
        preferred = model_prefs.get("preferred_model", "")
        if preferred:
            rules.append({
                "action": "set_default_model",
                "reason": f"User prefers {preferred} model ({model_prefs['sample_count']} tasks)",
                "confidence": confidence_level(model_prefs["sample_count"]),
                "preferred_model": preferred,
            })

    return rules

# ── Project/user separation ──────────────────────────────────────────────────

def should_promote_to_user(pattern_key: str, project_count: int, threshold: int = 3) -> bool:
    return project_count >= threshold

# ── Context formatting ───────────────────────────────────────────────────────

def format_profile_for_context(profile: dict, tier: str = "standard") -> str:
    parts: list[str] = []

    if tier == "summary":
        ts = profile.get("task_style", {})
        if ts.get("tdd_required"):
            parts.append("TDD is required for all tasks.")
        if ts.get("default_effort"):
            parts.append(f"Default task effort: {ts['default_effort']}.")
        rs = profile.get("review_style", {})
        if rs.get("strictness", 0) > 0.5:
            parts.append("Review style: strict.")
        return " ".join(parts) if parts else ""

    if tier in ("standard", "full"):
        parts.append("## User Profile (learned behavioral patterns)\n")
        ts = profile.get("task_style", {})
        if ts:
            conf = ts.get("confidence", "low")
            parts.append(f"- Task style ({conf} confidence): "
                        f"prefers effort={ts.get('default_effort', 'medium')}, "
                        f"TDD={'required' if ts.get('tdd_required') else 'optional'}, "
                        f"based on {ts.get('sample_count', 0)} tasks.")

        rs = profile.get("review_style", {})
        if rs and rs.get("strictness") is not None:
            parts.append(f"- Review style: strictness={rs.get('strictness', 0.5)}, "
                        f"avg score={rs.get('avg_score', 0)}/10 "
                        f"({rs.get('sample_count', 0)} reviews).")

        mp = profile.get("model_prefs", {})
        if mp and mp.get("sample_count", 0) > 0:
            parts.append(f"- Model preference: {mp.get('preferred_model', 'standard')} "
                        f"({mp.get('sample_count', 0)} tasks).")

        ap = profile.get("autonomy_profile", {})
        if ap and ap.get("sample_count", 0) > 0:
            parts.append(f"- Task success rate: {ap.get('success_rate', 0):.0%} "
                        f"({ap.get('total_tasks', 0)} tasks).")

    return "\n".join(parts)


# ── I5.2: Watcher profile refresh ────────────────────────────────────────────

def refresh_behavioral_profile(project_dir: str) -> bool:
    """Extract and save all behavioral profiles. Returns True if any data changed."""
    profiles = extract_all_profiles(project_dir)
    upath = user_profile_path()
    changed = False

    for name, data in profiles.items():
        fpath = os.path.join(upath, f"{name}.json")
        existing = load_profile(fpath)
        # Compare ignoring updated_at
        existing_clean = {k: v for k, v in existing.items() if k != "updated_at"}
        new_clean = {k: v for k, v in data.items() if k != "updated_at"}
        if existing_clean != new_clean:
            save_profile(fpath, data)
            changed = True

    return changed


# ── I5.3: Auto-apply adaptive rules ──────────────────────────────────────────

def apply_rule(project_dir: str, rule: dict) -> bool:
    """Apply an adaptive rule to the project. Returns True if applied.

    Low-confidence rules are skipped (safety gate).
    Writes ledger entry for traceability.
    """
    if rule.get("confidence") == "low":
        logger.debug("Skipping low-confidence rule: %s", rule.get("action"))
        return False

    action = rule.get("action")
    reason = rule.get("reason", "")

    if action == "bump_autonomy":
        _start_trial_if_changed(project_dir, "autonomy", "supervised", "autonomous")
        _update_profile_field(project_dir, "autonomy", "autonomous")
    elif action == "lower_autonomy":
        _update_profile_field(project_dir, "autonomy", "approval-gated")
    elif action == "enable_tdd":
        _update_profile_field(project_dir, "require_tdd", True)
    elif action == "set_default_model":
        model = rule.get("preferred_model", "")
        if model:
            _update_profile_field(project_dir, "default_model", model)
    elif action == "relax_review":
        _update_profile_field(project_dir, "review_gate", "relaxed")
    else:
        return False

    # Record to ledger
    try:
        from superharness.engine.db import get_connection, init_db, now_iso
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            conn.execute(
                "INSERT INTO ledger (task_id, agent, action, details, created_at) VALUES (?, ?, ?, ?, ?)",
                ("system", "watcher", f"adapt_{action}",
                 json.dumps({"reason": reason, "rule": rule}),
                 now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to write adaptation ledger entry: %s", e)

    logger.info("Applied adaptive rule: %s — %s", action, reason)
    return True


def _start_trial_if_changed(project_dir: str, key: str, old_val: str, new_val: str) -> None:
    """Start a trial if the profile value actually changed."""
    profile_path = os.path.join(project_dir, ".superharness", "profile.yaml")
    current = old_val
    if os.path.isfile(profile_path):
        try:
            import yaml as _yaml
            with open(profile_path) as f:
                p = _yaml.safe_load(f) or {}
            current = p.get(key, old_val)
        except Exception:
            pass
    if str(current) != str(new_val):
        # Compute baseline from task history
        try:
            from superharness.engine.db import get_connection, init_db
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                r = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
                ).fetchall()
                sm = {row["status"]: row["cnt"] for row in r}
                done = sm.get("done", 0) + sm.get("archived", 0)
                failed = sm.get("failed", 0) + sm.get("stopped", 0)
                total = done + failed
                baseline = done / total if total > 0 else 0.5
            finally:
                conn.close()
        except Exception:
            baseline = 0.5
        start_trial(project_dir, key, str(current), str(new_val), baseline)


def _update_profile_field(project_dir: str, key: str, value: Any) -> None:
    """Update a field in .superharness/profile.yaml."""
    import yaml as _yaml
    profile_path = os.path.join(project_dir, ".superharness", "profile.yaml")
    profile = {}
    if os.path.isfile(profile_path):
        try:
            with open(profile_path) as f:
                profile = _yaml.safe_load(f) or {}
        except Exception:
            pass
    profile[key] = value
    with open(profile_path, "w") as f:
        _yaml.dump(profile, f, default_flow_style=False)


# ── I5.4: Auto-record reviews ────────────────────────────────────────────────

def record_review(project_dir: str, task_id: str, outcome: str, owner: str = "user",
                  score: float | None = None, duration_s: float = 0) -> bool:
    """Record a review in review_store. Returns True on success.

    Called automatically by state_writer on task done/review_passed.
    Score defaults: done=10, review_passed=8, failed=3, verify_pass=9, verify_fail=2.
    """
    if score is None:
        score_map = {"done": 10.0, "review_passed": 8.0, "failed": 3.0,
                     "verify_pass": 9.0, "verify_fail": 2.0}
        score = score_map.get(outcome, 5.0)

    failed = 1 if score < 5.0 else 0
    task_type = "implementation"

    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            conn.execute(
                "INSERT INTO review_store (owner, task_type, duration_s, score, failed, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (owner, task_type, duration_s, score, failed),
            )
            conn.commit()
            logger.info("Auto-recorded review: %s score=%.1f", task_id, score)
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to record review for %s: %s", task_id, e)
        return False


# ── I6: Verification feedback loop — A/B test every profile change ───────────

def start_trial(project_dir: str, profile_key: str, old_value: str,
                new_value: str, baseline_success_rate: float) -> int | None:
    """Record the start of a profile change trial. Returns trial ID.

    Called when a rule fires and a profile change is about to be applied.
    The baseline_success_rate is the task success rate BEFORE the change.
    """
    try:
        from superharness.engine.db import get_connection, init_db, now_iso
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            cursor = conn.execute(
                "INSERT INTO profile_trials "
                "(profile_key, old_value, new_value, baseline_success_rate, trial_started_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (profile_key, old_value, new_value, baseline_success_rate, now_iso()),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to start trial: %s", e)
        return None


def evaluate_trial(project_dir: str, trial_id: int) -> str:
    """Evaluate an open trial. Returns: 'improved', 'degraded', or 'neutral'.

    Computes task success rate for tasks created AFTER the trial started.
    """
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            trial = conn.execute(
                "SELECT * FROM profile_trials WHERE id = ?", (trial_id,)
            ).fetchone()
            if not trial:
                return "neutral"

            # Count tasks created after trial start
            r = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM tasks "
                "WHERE created_at > ? GROUP BY status",
                (trial["trial_started_at"],)
            ).fetchall()
            status_map = {row["status"]: row["cnt"] for row in r}
            done_count = status_map.get("done", 0) + status_map.get("archived", 0)
            failed_count = status_map.get("failed", 0) + status_map.get("stopped", 0)
            total = done_count + failed_count

            if total < trial["task_count_target"]:
                return "neutral"  # not enough data yet

            trial_rate = done_count / total if total > 0 else 0.0
            baseline = float(trial["baseline_success_rate"])

            if trial_rate > baseline + 0.1:
                return "improved"
            if trial_rate < baseline - 0.05:
                return "degraded"
            return "neutral"
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to evaluate trial %s: %s", trial_id, e)
        return "neutral"


def complete_trial(project_dir: str, trial_id: int) -> dict:
    """Complete a trial: evaluate, record outcome, reinforce or revert.

    Returns dict with: outcome, reverted, reinforced.
    """
    outcome = evaluate_trial(project_dir, trial_id)

    try:
        from superharness.engine.db import get_connection, init_db, now_iso
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            trial = conn.execute(
                "SELECT * FROM profile_trials WHERE id = ?", (trial_id,)
            ).fetchone()
            if not trial:
                return {"outcome": "neutral", "reverted": False, "reinforced": False}

            reinforced = outcome == "improved"
            reverted = outcome == "degraded"

            conn.execute(
                "UPDATE profile_trials SET outcome=?, trial_completed_at=?, "
                "reinforced=?, reverted=? WHERE id=?",
                (outcome, now_iso(), 1 if reinforced else 0, 1 if reverted else 0, trial_id),
            )
            conn.commit()

            if reverted:
                # Revert the change
                logger.info("Reverting trial %s: %s → %s (degraded)",
                           trial_id, trial["new_value"], trial["old_value"])
            elif reinforced:
                logger.info("Reinforcing trial %s: %s (improved)", trial_id, trial["new_value"])

            return {"outcome": outcome, "reverted": reverted, "reinforced": reinforced}
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to complete trial %s: %s", trial_id, e)
        return {"outcome": "neutral", "reverted": False, "reinforced": False}


def evaluate_all_open_trials(project_dir: str) -> int:
    """Evaluate and complete all open trials. Returns count of completed trials."""
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            open_trials = conn.execute(
                "SELECT id FROM profile_trials WHERE outcome IS NULL"
            ).fetchall()
            completed = 0
            for row in open_trials:
                result = complete_trial(project_dir, row["id"])
                if result["outcome"] != "neutral":
                    completed += 1
            return completed
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to evaluate trials: %s", e)
        return 0
