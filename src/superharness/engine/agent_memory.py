"""Agent-writable memory — two-tier (global + per-project) learning system.

Adapted from Hermes agent MEMORY.md pattern. Superharness adaptation:
- Global tier: ~/.config/superharness/memory/ (machine-wide, all projects)
- Project tier: .superharness/memory/ (project-specific)
- Watcher injects both tiers into dispatch context
- Agents append to project memory during sessions
- Auto-promotion from project → global after N occurrences (Iteration 3)
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GLOBAL_MEMORY_DIR = os.path.join(
    os.path.expanduser("~"), ".config", "superharness", "memory"
)
PROJECT_ROOTS_FILE = os.path.join(
    os.path.expanduser("~"), ".config", "superharness", "project-roots.json"
)

GLOBAL_MEMORY_FILES = ("patterns.md", "pitfalls.md", "conventions.md")
PROJECT_MEMORY_FILES = ("conventions.md", "decisions.md", "pitfalls.md")
MEMORY_FILE_MAX_CHARS = 5_000  # FIFO prune oldest lines when exceeded

# Confidence-aware cap for the distilled index (pitfalls.md). Distilled lines
# are evicted lowest-confidence/oldest first; manual lines are never evicted.
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25_000


def _prune_if_over_limit(filepath: str) -> None:
    """FIFO prune: drop oldest content lines when file exceeds MEMORY_FILE_MAX_CHARS."""
    if not os.path.isfile(filepath):
        return
    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except Exception:
        return
    if len(content) <= MEMORY_FILE_MAX_CHARS:
        return

    lines = content.splitlines()
    # Keep header lines (starting with #)
    header = [l for l in lines if l.startswith("#")]
    body = [l for l in lines if not l.startswith("#") and l.strip()]

    # Trim from the beginning (oldest first) until under limit
    while body and len("\n".join(header + body)) + len(header) > MEMORY_FILE_MAX_CHARS:
        body.pop(0)

    result = "\n".join(header + [""] + body) + "\n"
    Path(filepath).write_text(result, encoding="utf-8")
    if len(body) < len([l for l in lines if not l.startswith("#") and l.strip()]):
        logger.info("Pruned memory file %s: %d → %d chars",
                     os.path.basename(filepath), len(content), len(result))


def global_memory_dir() -> str:
    """Return (and create if needed) the global memory directory."""
    os.makedirs(GLOBAL_MEMORY_DIR, exist_ok=True)
    return GLOBAL_MEMORY_DIR


def project_memory_dir(project_dir: str) -> str:
    """Return (and create if needed) the project memory directory."""
    pdir = os.path.join(project_dir, ".superharness", "memory")
    os.makedirs(pdir, exist_ok=True)
    return pdir


def _ensure_default_files(dirpath: str, filenames: tuple[str, ...]) -> None:
    """Create default memory files if they don't exist."""
    for fname in filenames:
        fpath = os.path.join(dirpath, fname)
        if not os.path.isfile(fpath):
            Path(fpath).write_text(f"# {fname.replace('.md', '').replace('_', ' ').title()}\n\n", encoding="utf-8")


def ensure_global_memory() -> str:
    """Ensure global memory directory and default files exist."""
    gdir = global_memory_dir()
    _ensure_default_files(gdir, GLOBAL_MEMORY_FILES)
    return gdir


def ensure_project_memory(project_dir: str) -> str:
    """Ensure project memory directory and default files exist."""
    pdir = project_memory_dir(project_dir)
    _ensure_default_files(pdir, PROJECT_MEMORY_FILES)
    return pdir


def _prepend_timestamp(content: str) -> str:
    """Prepend an ISO date prefix if not already present."""
    if content.strip().startswith(("202", "203")):
        return content
    today = datetime.now().strftime("%Y-%m-%d")
    return f"{today}: {content}"


def append(project_dir: str, filename: str, content: str) -> None:
    """Append a memory entry to a project memory file.

    Called by agents during sessions to record learned patterns.
    The content is timestamped if not already dated.
    """
    ensure_project_memory(project_dir)
    fpath = os.path.join(project_memory_dir(project_dir), filename)
    entry = _prepend_timestamp(content.strip()) + "\n"
    with open(fpath, "a", encoding="utf-8") as f:
        f.write(entry)
    if os.path.basename(filename) == DISTILL_TARGET_FILE:
        _cap_index(fpath)
    else:
        _prune_if_over_limit(fpath)
    logger.info("Agent memory appended to %s/%s", os.path.basename(project_dir), filename)


def append_global_override(override_dir: str, filename: str, content: str) -> None:
    """Append to global memory using a specific directory (for testing)."""
    os.makedirs(override_dir, exist_ok=True)
    fpath = os.path.join(override_dir, filename)
    if not os.path.isfile(fpath):
        Path(fpath).write_text(f"# {filename.replace('.md', '').title()}\n\n", encoding="utf-8")
    entry = _prepend_timestamp(content.strip()) + "\n"
    with open(fpath, "a", encoding="utf-8") as f:
        f.write(entry)
    if os.path.basename(filename) == DISTILL_TARGET_FILE:
        _cap_index(fpath)
    else:
        _prune_if_over_limit(fpath)


def _read_memory_file(filepath: str) -> str:
    """Read a memory file, returning non-header content."""
    if not os.path.isfile(filepath):
        return ""
    try:
        lines = Path(filepath).read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    # Skip header lines (starting with #)
    content_lines = [l for l in lines if not l.startswith("#") and l.strip()]
    return "\n".join(content_lines)


# ---------------------------------------------------------------------------
# Distilled lessons — confidence-tagged, deduped, conflict-aware (Iteration 3)
# ---------------------------------------------------------------------------

DISTILL_TARGET_FILE = "pitfalls.md"

# - [c=0.80 src=distill 2026-06-23] <lesson text>
_LESSON_RE = re.compile(
    r"^- \[c=(?P<conf>[0-9.]+) src=(?P<src>\S+) (?P<date>\d{4}-\d{2}-\d{2})\] (?P<text>.+)$"
)


def format_lesson_line(entry) -> str:
    """Render a distilled lesson as a confidence-tagged bullet line.

    `entry` is duck-typed: needs .text, .confidence, .source, and (optional) .date.
    """
    d = getattr(entry, "date", "") or datetime.now().strftime("%Y-%m-%d")
    return f"- [c={float(entry.confidence):.2f} src={entry.source} {d}] {entry.text.strip()}"


def parse_lesson_line(line: str) -> tuple[str, float | None]:
    """Parse a memory line into (text, confidence).

    Tagged distilled lines yield their confidence; untagged manual lines (and
    anything unparseable) yield confidence None, marking them authoritative —
    apply never overwrites them.
    """
    m = _LESSON_RE.match(line.strip())
    if m:
        try:
            return m.group("text").strip(), float(m.group("conf"))
        except ValueError:
            pass
    return line.strip(), None


def _normalize_key(text: str) -> str:
    """Dedup key: strip bullet/date prefixes, lowercase, collapse whitespace."""
    t = text.strip()
    t = re.sub(r"^-\s+", "", t)
    t = re.sub(r"^\d{4}-\d{2}-\d{2}:\s*", "", t)
    return re.sub(r"\s+", " ", t.lower())


def apply_lessons(lessons, project_dir: str, *, target_dir: str | None = None) -> int:
    """Persist distilled lessons to the project pitfalls.md, confidence-gated.

    Rules:
    - dedup by normalized text
    - never overwrite a manual (untagged) line — it is authoritative
    - overwrite an existing distilled line only with strictly higher confidence
    Returns the number of lines written (new or replaced). Does not create the
    file when nothing is written.
    """
    if not lessons:
        return 0

    mem_dir = target_dir or project_memory_dir(project_dir)
    os.makedirs(mem_dir, exist_ok=True)
    fpath = os.path.join(mem_dir, DISTILL_TARGET_FILE)

    header_lines: list[str] = ["# Pitfalls", ""]
    # entries: [raw_line, normalized_key, confidence|None]
    entries: list[list] = []
    if os.path.isfile(fpath):
        all_lines = Path(fpath).read_text(encoding="utf-8").splitlines()
        hdr = [l for l in all_lines if l.startswith("#")]
        if hdr:
            header_lines = hdr + [""]
        for raw in all_lines:
            if not raw.strip() or raw.startswith("#"):
                continue
            text, conf = parse_lesson_line(raw)
            entries.append([raw, _normalize_key(text), conf])

    written = 0
    for lesson in lessons:
        key = _normalize_key(lesson.text)
        match = next((e for e in entries if e[1] == key), None)
        if match is None:
            entries.append([format_lesson_line(lesson), key, float(lesson.confidence)])
            written += 1
        elif match[2] is None:
            continue  # manual line — preserve, skip incoming
        elif float(lesson.confidence) > match[2]:
            match[0] = format_lesson_line(lesson)
            match[2] = float(lesson.confidence)
            written += 1
        # else: existing confidence >= incoming → skip

    if written == 0:
        return 0

    body = "\n".join(e[0] for e in entries)
    Path(fpath).write_text("\n".join(header_lines) + body + "\n", encoding="utf-8")
    _cap_index(fpath)
    logger.info("Distilled %d lesson(s) into %s", written, fpath)
    return written


def _cap_index(filepath: str) -> None:
    """Confidence-aware cap for the distilled index (pitfalls.md).

    Holds the file to MAX_INDEX_LINES / MAX_INDEX_BYTES by evicting distilled
    lines lowest-confidence/oldest first. Manual (untagged) lines are never
    evicted — if they alone exceed the cap they are kept (and logged), not
    silently truncated. No-op when already under both caps.
    """
    if not os.path.isfile(filepath):
        return
    try:
        all_lines = Path(filepath).read_text(encoding="utf-8").splitlines()
    except Exception:
        return

    header = [l for l in all_lines if l.startswith("#")]
    body = [l for l in all_lines if l.strip() and not l.startswith("#")]
    if not header:
        header = ["# Pitfalls"]
    header_block = header + [""]

    base_bytes = len(("\n".join(header_block)).encode()) + 1  # trailing newline
    total_bytes = base_bytes + sum(len(l.encode()) + 1 for l in body)
    if len(body) <= MAX_INDEX_LINES and total_bytes <= MAX_INDEX_BYTES:
        return  # under both caps — leave untouched

    manual: list[str] = []
    distilled: list[tuple[str, float, str]] = []
    for raw in body:
        _text, conf = parse_lesson_line(raw)
        if conf is None:
            manual.append(raw)
        else:
            m = _LESSON_RE.match(raw.strip())
            distilled.append((raw, conf, m.group("date") if m else ""))

    # Keep best first: highest confidence, then most recent.
    distilled.sort(key=lambda x: (x[1], x[2]), reverse=True)

    final = list(manual)
    cur_lines = len(final)
    cur_bytes = base_bytes + sum(len(l.encode()) + 1 for l in final)
    manual_over = cur_lines > MAX_INDEX_LINES or cur_bytes > MAX_INDEX_BYTES
    if manual_over:
        logger.warning(
            "pitfalls index exceeds cap on manual lines alone (%d lines); "
            "keeping manual, dropping all distilled", cur_lines
        )
    else:
        for raw, _conf, _date in distilled:
            add_bytes = len(raw.encode()) + 1
            if cur_lines + 1 <= MAX_INDEX_LINES and cur_bytes + add_bytes <= MAX_INDEX_BYTES:
                final.append(raw)
                cur_lines += 1
                cur_bytes += add_bytes
            else:
                break  # sorted best-first; everything after is worse

    Path(filepath).write_text("\n".join(header_block) + "\n".join(final) + "\n", encoding="utf-8")


def _deduplicate_content(content: str) -> str:
    """Collapse identical lines into one with a count. Single occurrences unchanged.

    "avoid X\navoid X\navoid X\nuse Y\n" → "avoid X (seen 3 times)\nuse Y\n"
    """
    if not content:
        return ""
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    if not lines:
        return ""
    from collections import Counter
    counts = Counter(lines)
    result = []
    for line, count in counts.most_common():
        if count > 1:
            result.append(f"{line} (seen {count} times)")
        else:
            result.append(line)
    return "\n".join(result)


def get_dispatch_memory_context(project_dir: str) -> str:
    """Return memory content for injection into agent dispatch context.

    Reads global memory first (machine-wide patterns), then project memory
    (project-specific conventions/decisions). Returns a formatted string
    ready for inclusion in the dispatch prompt.
    """
    parts: list[str] = []

    # Global memory
    ensure_global_memory()
    global_content: list[str] = []
    for fname in GLOBAL_MEMORY_FILES:
        content = _read_memory_file(os.path.join(GLOBAL_MEMORY_DIR, fname))
        if content:
            global_content.append(_deduplicate_content(content))

    if global_content:
        parts.append("## Global Learning (from all projects on this machine)")
        parts.append("\n".join(global_content))

    # Project memory
    if os.path.isdir(os.path.join(project_dir, ".superharness")):
        ensure_project_memory(project_dir)
        pdir = project_memory_dir(project_dir)
        local_content: list[str] = []
        for fname in PROJECT_MEMORY_FILES:
            content = _read_memory_file(os.path.join(pdir, fname))
            if content:
                local_content.append(content)

        if local_content:
            parts.append(f"\n## Project Memory ({os.path.basename(project_dir)})")
            parts.append("\n".join(local_content))

    return "\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Auto-promotion: project memory → global memory (Hermes adaptation)
# ---------------------------------------------------------------------------

PROMOTION_THRESHOLD = 3


def _count_pattern_occurrences(memory_dir: str, filename: str, pattern: str) -> int:
    """Count how many times a pattern appears in a memory file."""
    fpath = os.path.join(memory_dir, filename)
    if not os.path.isfile(fpath):
        return 0
    try:
        content = Path(fpath).read_text(encoding="utf-8")
    except Exception:
        return 0
    # Count lines that contain the pattern (case-insensitive, stripped)
    count = 0
    pattern_lower = pattern.strip().lower()
    for line in content.splitlines():
        if pattern_lower in line.strip().lower():
            count += 1
    return count


def _load_project_roots() -> list[str]:
    """Load project root directories from config file. Returns empty list if missing."""
    if not os.path.isfile(PROJECT_ROOTS_FILE):
        return []
    try:
        data = json.loads(Path(PROJECT_ROOTS_FILE).read_text(encoding="utf-8"))
        roots = data.get("scan_roots", [])
        return [os.path.expanduser(r) for r in roots if isinstance(r, str)]
    except (json.JSONDecodeError, KeyError, OSError):
        return []


def _count_pattern_across_all_projects(filename: str, pattern: str, *, global_override: str | None = None) -> int:
    """Count pattern occurrences across all known project memory directories."""
    total = 0
    gdir = global_override or GLOBAL_MEMORY_DIR
    gpath = os.path.join(gdir, filename)
    if os.path.isfile(gpath):
        total += _count_pattern_occurrences(gdir, filename, pattern)

    roots = _load_project_roots()
    if roots:
        for root in roots:
            if not os.path.isdir(root):
                continue
            try:
                for entry in os.scandir(root):
                    if not entry.is_dir():
                        continue
                    mem_dir = os.path.join(entry.path, ".superharness", "memory")
                    if os.path.isdir(mem_dir):
                        total += _count_pattern_occurrences(mem_dir, filename, pattern)
            except PermissionError:
                continue

    return total


def _count_pattern_across_sibling_projects(project_dir: str, filename: str, pattern: str, *, global_override: str | None = None) -> int:
    """Count pattern occurrences across sibling project directories + global.

    When global_override is set (test mode), skips sibling scanning to avoid
    cross-test contamination from other pytest temp directories.
    """
    total = _count_pattern_across_all_projects(filename, pattern, global_override=global_override)

    # Skip sibling scan in test mode (global_override set) — prevents
    # counting patterns from other pytest temp directories as false positives.
    if global_override is not None:
        return total
    parent = os.path.dirname(os.path.realpath(project_dir))
    if os.path.isdir(parent):
        try:
            for entry in os.scandir(parent):
                if not entry.is_dir():
                    continue
                mem_dir = os.path.join(entry.path, ".superharness", "memory")
                if os.path.isdir(mem_dir):
                    total += _count_pattern_occurrences(mem_dir, filename, pattern)
        except PermissionError:
            pass
    return total


def _is_project_specific(pattern: str, project_dir: str) -> bool:
    """Return True if the pattern contains project-specific path references."""
    norm_project = os.path.realpath(project_dir).lower()
    norm_pattern = pattern.lower()
    return norm_project in norm_pattern


def promote_to_global(
    project_dir: str,
    filename: str,
    *,
    global_override: str | None = None,
) -> bool:
    """Promote a memory file's patterns to global memory.

    Scans the given project memory file for patterns with ≥PROMOTION_THRESHOLD
    occurrences that are NOT project-specific, and copies them to the
    corresponding global memory file.

    Returns True if any patterns were promoted.
    """
    pdir = project_memory_dir(project_dir)
    fpath = os.path.join(pdir, filename)
    if not os.path.isfile(fpath):
        return False

    gdir = global_override or GLOBAL_MEMORY_DIR
    os.makedirs(gdir, exist_ok=True)
    gpath = os.path.join(gdir, filename)
    if not os.path.isfile(gpath):
        Path(gpath).write_text(f"# {filename.replace('.md', '').title()}\n\n", encoding="utf-8")

    promoted_any = False

    try:
        lines = [l for l in Path(fpath).read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
    except Exception:
        return False

    # Collect unique patterns with their counts
    from collections import Counter
    stripped = [line.strip() for line in lines]
    pattern_counts = Counter(stripped)

    for pattern, count in pattern_counts.most_common():
        # Cross-project count: single-project occurrences + global + other projects
        cross_count = _count_pattern_across_sibling_projects(
            project_dir, filename, pattern, global_override=global_override
        )
        effective_count = max(count, cross_count)

        if effective_count < PROMOTION_THRESHOLD:
            continue
        if _is_project_specific(pattern, project_dir):
            continue
        # Check if already in global
        existing = Path(gpath).read_text(encoding="utf-8")
        if pattern.strip().lower() in existing.lower():
            continue
        # Promote
        with open(gpath, "a", encoding="utf-8") as f:
            f.write(pattern + "\n")
        _prune_if_over_limit(gpath)
        logger.info("Promoted pattern to global memory (count=%d across %d): %s",
                    effective_count, cross_count, pattern[:80])
        promoted_any = True

    return promoted_any


def promote_all_project_memory(project_dir: str) -> int:
    """Run promotion on all project memory files. Returns count of files with promotions."""
    promoted_files = 0
    for fname in PROJECT_MEMORY_FILES:
        if promote_to_global(project_dir, fname):
            promoted_files += 1
    return promoted_files


# ---------------------------------------------------------------------------
# Project roots management — config file for cross-project scanning
# ---------------------------------------------------------------------------

def list_project_roots() -> list[str]:
    """Return the configured project root directories."""
    return _load_project_roots()


def add_project_root(path: str) -> bool:
    """Add a directory to the project roots config. Returns True if added."""
    resolved = os.path.realpath(os.path.expanduser(path))
    if not os.path.isdir(resolved):
        return False

    roots = _load_project_roots()
    if resolved in roots:
        return False  # already present

    roots.append(resolved)
    _save_project_roots(roots)
    return True


def remove_project_root(path: str) -> bool:
    """Remove a directory from project roots. Returns True if removed."""
    resolved = os.path.realpath(os.path.expanduser(path))
    roots = _load_project_roots()
    if resolved not in roots:
        return False  # not present

    roots.remove(resolved)
    _save_project_roots(roots)
    return True


def _save_project_roots(roots: list[str]) -> None:
    """Persist project roots to the config file."""
    os.makedirs(os.path.dirname(PROJECT_ROOTS_FILE), exist_ok=True)
    Path(PROJECT_ROOTS_FILE).write_text(
        json.dumps({"scan_roots": roots}, indent=2) + "\n",
        encoding="utf-8",
    )
