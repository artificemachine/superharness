"""Skill YAML loader — reusable agent workflows.

Cherry-picked from hermes-agent/agent/skill_commands.py.
"""
import os
import yaml


def load_skill(project_dir: str, name: str) -> dict | None:
    """Load a skill YAML from .superharness/skills/<name>.yaml."""
    path = os.path.join(project_dir, ".superharness", "skills", f"{name}.yaml")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def save_skill(project_dir: str, name: str, skill: dict) -> bool:
    """Save a skill to .superharness/skills/<name>.yaml."""
    skills_dir = os.path.join(project_dir, ".superharness", "skills")
    os.makedirs(skills_dir, exist_ok=True)
    path = os.path.join(skills_dir, f"{name}.yaml")
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(skill, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception:
        return False


def discover_skills(project_dir: str, tags: list[str] | None = None) -> list[dict]:
    """Find skills matching given tags. Returns list of skill dicts."""
    skills_dir = os.path.join(project_dir, ".superharness", "skills")
    if not os.path.isdir(skills_dir):
        return []
    results = []
    for fname in sorted(os.listdir(skills_dir)):
        if not fname.endswith(".yaml"):
            continue
        skill = load_skill(project_dir, fname[:-5])
        if skill is None:
            continue
        if tags:
            skill_tags = skill.get("tags", [])
            if not any(t in skill_tags for t in tags):
                continue
        results.append(skill)
    return results


def list_skill_names(project_dir: str) -> list[str]:
    """List all saved skill names."""
    skills_dir = os.path.join(project_dir, ".superharness", "skills")
    if not os.path.isdir(skills_dir):
        return []
    return sorted(f[:-5] for f in os.listdir(skills_dir) if f.endswith(".yaml"))


def delete_skill(project_dir: str, name: str) -> bool:
    """Delete a skill file."""
    path = os.path.join(project_dir, ".superharness", "skills", f"{name}.yaml")
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
