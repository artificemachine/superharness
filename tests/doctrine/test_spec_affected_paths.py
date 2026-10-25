"""Spec review freshness stays meaningful: no spec covers a file every commit changes."""

from pathlib import Path

SPECS = Path(__file__).resolve().parents[2] / "docs" / "specs"

# Every commit appends to CHANGELOG.md (pre-commit check 1b.1), so a spec that
# lists it goes stale for the doctrine guard on the first commit made on a day
# after its review, whatever that commit touches.
CHANGED_BY_EVERY_COMMIT = {"CHANGELOG.md"}


def _affected_paths(spec: Path) -> set[str]:
    for line in spec.read_text().splitlines():
        if line.startswith("Affected paths: "):
            return {p.strip() for p in line.removeprefix("Affected paths: ").split(",")}
    return set()


def test_no_spec_covers_a_file_changed_by_every_commit() -> None:
    offenders = {
        spec.name: sorted(_affected_paths(spec) & CHANGED_BY_EVERY_COMMIT)
        for spec in sorted(SPECS.glob("SPEC-*.md"))
        if _affected_paths(spec) & CHANGED_BY_EVERY_COMMIT
    }
    assert not offenders, (
        f"specs declare paths that every commit changes, so their review is "
        f"always stale: {offenders}"
    )
