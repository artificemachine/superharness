"""Iteration 5 of PLAN-coding-practices.md — cheap counting guards that make
iterations 1 through 4 permanent.

Each ceiling below was measured fresh against the working tree at the time
this file was written (not copied from the plan, per its own recheck
instruction — the plan's numbers had already moved by the time iterations
1-4 landed). A ceiling may only go down in a future commit; if a change
needs to raise one, that is a deliberate, reviewable decision, not a silent
drift.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "superharness"

# Guards the PR #58 root cause: sys.exit() calls scattered through engine/
# instead of raising domain errors caught at the CLI boundary. Iteration 6
# migrated the 19 low-risk sites (contract.py, recall.py, validate.py,
# profile.py, operator.py, detect.py) behind engine/errors.py, whose
# handle_cli_error is the one legitimate remaining call — hence 88 - 19 + 1.
# Iteration 7 migrated the last 69 sites (discussion.py 38, inbox.py 23,
# discuss.py 8), landing on the theoretical floor: engine/errors.py's own
# handle_cli_error is the only file under engine/ that may ever contain the
# literal text "sys.exit" again — every other engine/ module raises a
# SuperharnessError and lets a CLI boundary (a module's own __main__ guard,
# or an in-process caller like cli.py / commands/discuss.py) convert it.
_SYS_EXIT_IN_ENGINE_CEILING = 1

# Guards silently-swallowed errors (the "dead scanner" class of bug).
# 728 was iteration 5's fresh measurement (the audit doc's authoring-time
# 205 did not reproduce — see git history for that investigation). Iteration
# 8 narrowed 4 sites in the three highest-count files (2 in
# commands/inbox_watch.py's os.kill() calls, 1 in the same file's ledger
# append, 1 in scripts/dashboard-ui.py's `import yaml` probe) from a broad
# catch to the specific exception each site can actually raise, and found
# and fixed a genuine pre-existing bug along the way: commands/
# inbox_dispatch.py's _sqlite_mirror_dispatch had two stacked broad-catch
# clauses on the same try, so the second (which already had exc_info=True)
# was unreachable dead code. Merging that pair accounts for the fifth site
# of the drop from 728 to 723. See CONTRIBUTING.md's "Exception-handling
# policy" and tests/unit/test_broad_except_narrowing.py for the behavioural
# proof each narrowed site now lets an unrelated exception propagate
# instead of swallowing it.
_BROAD_EXCEPT_CEILING = 723

# The three files with the highest `except Exception` concentration,
# measured fresh for iteration 8 (132, 80, 33 respectively — not assumed
# from the plan's own guess, per its recheck instruction). Every remaining
# `except Exception` in these three files must log with exc_info=True; see
# CONTRIBUTING.md's "Exception-handling policy".
_EXC_INFO_ENFORCED_FILES = (
    "commands/inbox_watch.py",
    "scripts/dashboard-ui.py",
    "commands/inbox_dispatch.py",
)

# Guards god-file growth. inbox_watch.py is already the largest file in the
# tree by a wide margin (out of scope to split — see
# docs/AUDIT-coding-practices-2026-07-20.md "What not to do"); this ceiling
# stops it, and everything else, from growing further unnoticed.
# 2026-07-21: bumped 4720->4721, the exact +1 line cost of fixing a real
# NameError crash bug (inbox_watch.py:2968, _ledger_record2 called without
# the local import 3 sibling call sites in this file already have).
# 2026-07-21 (coding-practices iter8, combined with the bump above via
# rebase): raised again to 4788 — adding exc_info=True logging to 65
# previously-silent `except Exception` sites in inbox_watch.py is
# deliberate, reviewed growth, not drift — see CONTRIBUTING.md's
# "Exception-handling policy". 4788 is the exact measured total with both
# changes applied (`wc -l`), not padded.
_MAX_FILE_LINE_CEILING = 4788


def _count_matches(pattern: str, paths: list[Path]) -> int:
    regex = re.compile(pattern)
    total = 0
    for path in paths:
        total += len(regex.findall(path.read_text()))
    return total


def _all_src_files() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


def _engine_files() -> list[Path]:
    return sorted((SRC_ROOT / "engine").glob("*.py"))


def test_sys_exit_in_engine_does_not_grow():
    count = _count_matches(r"sys\.exit", _engine_files())
    assert count <= _SYS_EXIT_IN_ENGINE_CEILING, (
        f"sys.exit count in engine/ grew to {count} (ceiling "
        f"{_SYS_EXIT_IN_ENGINE_CEILING}). If this is a deliberate net-new "
        f"site, lower it by migrating an existing one first (see "
        f"PLAN-coding-practices.md iterations 6-7), or raise the ceiling "
        f"here as a reviewed, deliberate decision — never silently."
    )


def test_broad_except_does_not_grow():
    count = _count_matches(r"except Exception", _all_src_files())
    assert count <= _BROAD_EXCEPT_CEILING, (
        f"'except Exception' count grew to {count} (ceiling "
        f"{_BROAD_EXCEPT_CEILING}). See PLAN-coding-practices.md iteration 8 "
        f"for the narrowing policy; do not add a new broad catch without "
        f"logging exc_info=True at minimum."
    )


def test_no_file_exceeds_line_ceiling():
    """Per-file max, not a total — one file growing past the ceiling fails
    even if every other file shrank."""
    offenders = {}
    for path in _all_src_files():
        line_count = sum(1 for _ in path.open())
        if line_count > _MAX_FILE_LINE_CEILING:
            offenders[str(path.relative_to(REPO_ROOT))] = line_count
    assert not offenders, (
        f"file(s) exceeded the {_MAX_FILE_LINE_CEILING}-line ceiling: {offenders}"
    )


def _string_literal_value(node: ast.AST) -> str | None:
    """Best-effort extraction of a string literal's content, including the
    literal (non-interpolated) segments of an f-string. Returns None for
    anything that isn't a string constant or f-string (e.g. json.dumps(...),
    a variable, a format() call) — those can't be "generated Python source
    written as a string" in the sense this test guards against, since their
    content isn't visible as source text at all.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
        return "".join(parts)
    return None


def _generated_python_source_writes(path: Path) -> list[int]:
    """Line numbers of `.write_text(...)` calls whose argument is a string
    literal (or f-string) containing both "import " and "def " — the
    signature of a Python program embedded as a string, the exact shape of
    the daemon-monitor bug this plan's iteration 3 fixed."""
    tree = ast.parse(path.read_text(), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text" and node.args):
            continue
        text = _string_literal_value(node.args[0])
        if text is None:
            continue
        if "import " in text and "def " in text:
            offenders.append(node.lineno)
    return offenders


def test_no_python_source_generated_as_a_string():
    hits = {}
    for path in _all_src_files():
        offenders = _generated_python_source_writes(path)
        if offenders:
            hits[str(path.relative_to(REPO_ROOT))] = offenders
    assert not hits, (
        f"write_text() call(s) passing what looks like generated Python "
        f"source (a string literal containing both 'import ' and 'def '): "
        f"{hits}. This is the daemon-monitor-as-a-string shape iteration 3 "
        f"of PLAN-coding-practices.md removed — write real, importable "
        f"modules instead."
    )


def _bare_exception_handlers(tree: ast.AST) -> list[ast.ExceptHandler]:
    """Every `except Exception` (bare or `as name`) handler — NOT
    `except (Exception, X)` or a subclass, matching what the
    _BROAD_EXCEPT_CEILING regex itself counts as `except Exception`."""
    handlers = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name) \
                and node.type.id == "Exception":
            handlers.append(node)
    return handlers


def _handler_has_exc_info(handler: ast.ExceptHandler) -> bool:
    """True if any Call anywhere in the handler body passes an `exc_info`
    keyword argument — logger.warning(..., exc_info=True) is the documented
    shape (CONTRIBUTING.md), but this doesn't check the value, only that
    the keyword is present, matching the plan's own "carrying exc_info"
    wording for this test."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            if any(kw.arg == "exc_info" for kw in node.keywords):
                return True
    return False


def test_supervisory_excepts_log_with_exc_info():
    """Iteration 8: every `except Exception` remaining in the three
    highest-count files must log with exc_info=True — a supervisory
    boundary that swallows an error without a traceback is how a watcher
    tick or a dispatch step goes silently dead while still reporting
    "success" (the "dead scanner" bug class). See CONTRIBUTING.md's
    "Exception-handling policy"."""
    offenders: dict[str, list[int]] = {}
    for rel in _EXC_INFO_ENFORCED_FILES:
        path = SRC_ROOT / rel
        tree = ast.parse(path.read_text(), filename=str(path))
        missing = [
            h.lineno for h in _bare_exception_handlers(tree)
            if not _handler_has_exc_info(h)
        ]
        if missing:
            offenders[rel] = missing
    assert not offenders, (
        f"except Exception handler(s) without exc_info=True in the "
        f"exc_info-enforced files: {offenders}. See CONTRIBUTING.md's "
        f"Exception-handling policy — every broad except in these three "
        f"files must log with exc_info=True, or be narrowed to a specific "
        f"exception type."
    )


# ---------------------------------------------------------------------------
# Iteration 9 — coverage gate consistency
# ---------------------------------------------------------------------------

_COV_FAIL_UNDER_PATTERNS = (
    # pytest-cov CLI flag, as used in .github/workflows/*.yml
    re.compile(r"--cov-fail-under=(\d+)"),
    # coverage.py's own [tool.coverage.report] key, as used in pyproject.toml
    re.compile(r"^\s*fail_under\s*=\s*(\d+)\s*$", re.MULTILINE),
)


def _cov_fail_under_occurrences() -> dict[str, int]:
    """Every `cov-fail-under`/`fail_under` value found under .github/ and in
    pyproject.toml, keyed by "relative/path:line". Two different spellings
    for the same concept (a CLI flag in CI workflows, a native TOML key for
    local/IDE coverage runs) — both must agree, or CI and a local `pytest
    --cov` run silently enforce different floors."""
    occurrences: dict[str, int] = {}
    candidates = list((REPO_ROOT / ".github").rglob("*.yml")) + list((REPO_ROOT / ".github").rglob("*.yaml"))
    pyproject = REPO_ROOT / "pyproject.toml"
    if pyproject.is_file():
        candidates.append(pyproject)
    for path in candidates:
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in _COV_FAIL_UNDER_PATTERNS:
                m = pattern.search(line)
                if m:
                    key = f"{path.relative_to(REPO_ROOT)}:{lineno}"
                    occurrences[key] = int(m.group(1))
    return occurrences


def test_coverage_gate_is_consistent_across_workflows():
    """Every `cov-fail-under=N` / `fail_under = N` occurrence under
    .github/ or in pyproject.toml must carry the identical value. Guards
    the stale-pair failure mode where one of two (or more) identical CI
    lines is updated and the other is not — the exact gap iteration 9 of
    PLAN-coding-practices.md exists to close."""
    occurrences = _cov_fail_under_occurrences()
    assert occurrences, "expected at least one cov-fail-under/fail_under occurrence; found none"
    values = set(occurrences.values())
    assert len(values) == 1, (
        f"cov-fail-under/fail_under values disagree across the repo: {occurrences}. "
        f"Every occurrence must carry the same number — update all of them together."
    )
