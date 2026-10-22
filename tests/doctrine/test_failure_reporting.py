"""INV-2: every confirmed failure gets a written report and a labelled tracker issue."""

from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "docs" / "incidents" / "TEMPLATE.md"


def _section(text: str, heading: str) -> str:
    """Return the body of a `## heading` section, or "" when it is absent."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            body = []
            for following in lines[index + 1 :]:
                if following.startswith("## "):
                    break
                body.append(following)
            return "\n".join(body)
    return ""


def test_incident_template_has_tracker_section() -> None:
    """The incident template makes the tracker issue a required part of every report."""
    tracker = _section(TEMPLATE.read_text(), "Tracker")
    assert tracker.strip(), "docs/incidents/TEMPLATE.md has no non-empty '## Tracker' section"
    assert "AI-gen" in tracker, "Tracker section must require the AI-gen label"
    assert "queued" in tracker.lower(), (
        "Tracker section must say what happens when the tracker is unreachable"
    )
