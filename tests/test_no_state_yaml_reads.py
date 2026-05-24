"""Guard: enforce the "SQLite is source of truth" invariant for state READS.

Doctrine (engine/sqlite_only.py): all operational state lives in SQLite; YAML
files are export-only. This guard fails CI if code reads a SQLite-backed state
artifact (handoffs/*.yaml, ledger.md, contract.yaml, inbox.yaml, discussion
round/state YAML) as authoritative input.

Detection is a UNION of two scanners:
  - REGEX: catches direct idioms (`handoffs_dir.glob(`, `ledger.read_text()`).
  - AST taint: follows indirection regex can't — a helper that builds a state
    path, a var assigned from it, then a read on that var
    (`d = _handoffs_dir(p); os.listdir(d)`). This closes the former blind spots.

It is a RATCHET, not a hard wall: the repo currently has known violations
(see PLAN-sqlite-source-of-truth-refactor.md), captured in BASELINE below.
- A NEW offending file (not in BASELINE) -> test FAILS (no regressions).
- A BASELINE file that no longer offends -> test FAILS, demanding you remove it
  from BASELINE (the count can only go DOWN). The migration is provably complete
  only when BASELINE is empty.

Scope: READS only (the silent-success class). Operational YAML *writes* are
addressed by Phase 1 of the refactor and could get a sibling write-guard later.

Emitted by /bulletproof --emit-guard on 2026-05-22. Mutation-checked (literal,
variable, and helper-indirection forms).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# repo_root/tests/this_file -> repo_root/src/superharness
_SRC = Path(__file__).resolve().parent.parent / "src" / "superharness"
_SCAN_DIRS = ("commands", "engine", "mcp", "scripts")

# --- shared state vocabulary -------------------------------------------------
# State artifacts backed by SQLite. NOT config: profile/watcher/heartbeat/
# scheduled.yaml and agents/*.status.yaml are config and excluded by omission.
# "handoff" (singular) taints function parameters named handoff_dir/handoff_file.
_STATE_TOKENS = ("handoffs", "handoff", "ledger.md", "discussions", "contract.yaml",
                 "inbox.yaml", "state.yaml")

# Per-line opt-out for false positives (instruction strings, not real reads).
_IGNORE = re.compile(r"shipguard:ignore|export only|noqa: state-read")

# --- regex scanner (direct idioms) ------------------------------------------
_VIOLATION_PATTERNS = [
    re.compile(r"(handoffs|discussions)[^\n]{0,40}?\.(glob|iterdir)\("),
    re.compile(r"listdir\([^)]*(handoffs|discussions)"),
    re.compile(r"glob\.(glob|iglob)\([^)]*(handoffs|discussions)"),
    re.compile(r"ledger[A-Za-z_]*\.(read_text|readlines)\("),
    re.compile(r'open\([^)]*ledger[^)]*\.md'),
    re.compile(r'ledger\.md"\s*\)?\s*\.\s*read'),
]

# --- AST scanner (indirection via taint) ------------------------------------
_READ_METHODS = {"glob", "iterdir", "read_text", "read_bytes", "readlines"}
_PATH_BUILDERS = {"join", "Path", "PurePath"}


def _str_has_state(s: str) -> bool:
    return any(tok in s for tok in _STATE_TOKENS)


def _attr_name(f: ast.AST) -> str | None:
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _target_names(t: ast.AST) -> list[str]:
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, (ast.Tuple, ast.List)):
        out: list[str] = []
        for e in t.elts:
            out += _target_names(e)
        return out
    return []


def _is_state_expr(node: ast.AST, tainted: set[str], producers: set[str]) -> bool:
    """True if the expression yields a path to a SQLite-backed state artifact."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _str_has_state(node.value)
    if isinstance(node, ast.Name):
        return node.id in tainted
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):  # pathlib `/`
        return (_is_state_expr(node.left, tainted, producers)
                or _is_state_expr(node.right, tainted, producers))
    if isinstance(node, ast.JoinedStr):  # f-string with a literal state segment
        return any(isinstance(v, ast.Constant) and isinstance(v.value, str)
                   and _str_has_state(v.value) for v in node.values)
    if isinstance(node, ast.Call):
        name = _attr_name(node.func)
        if name in _PATH_BUILDERS:  # os.path.join(...), Path(...)
            return any(_is_state_expr(a, tainted, producers) for a in node.args)
        if name in producers:       # call to a helper that returns a state path
            return True
    return False


def _producers(tree: ast.AST) -> set[str]:
    """Function names whose return value builds a state path. Fixpoint so a
    producer that calls another producer is also recognised."""
    producers: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in producers:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Return) and sub.value is not None \
                            and _is_state_expr(sub.value, set(), producers):
                        producers.add(node.name)
                        changed = True
                        break
    return producers


def _tainted_vars(tree: ast.AST, producers: set[str]) -> set[str]:
    """Variables assigned (transitively) from a state-path expression.

    Also taints function parameters whose *name* contains a state token
    (e.g. handoff_dir, handoff_file) — these are the entry points where
    callers pass in state paths that the scanner cannot trace through call
    boundaries.
    """
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
    tainted: set[str] = set()
    # Seed: function parameters named after state artifacts
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args:
                if _str_has_state(arg.arg):
                    tainted.add(arg.arg)
    changed = True
    while changed:
        changed = False
        for a in assigns:
            if _is_state_expr(a.value, tainted, producers):
                for tgt in a.targets:
                    for name in _target_names(tgt):
                        if name not in tainted:
                            tainted.add(name)
                            changed = True
    return tainted


def _read_lineno(node: ast.Call, tainted: set[str], producers: set[str]) -> int | None:
    f = node.func
    # method reads: <tainted>.glob() / .read_text() / .readlines() / .iterdir()
    if isinstance(f, ast.Attribute) and f.attr in _READ_METHODS:
        if _is_state_expr(f.value, tainted, producers):
            return node.lineno
    # glob.glob(arg) / glob.iglob(arg) — also catches aliased imports (import glob as _glob)
    if isinstance(f, ast.Attribute) and f.attr in ("glob", "iglob"):
        if node.args and _is_state_expr(node.args[0], tainted, producers):
            return node.lineno
    # os.listdir(arg) / listdir(arg)
    if _attr_name(f) == "listdir" and node.args and _is_state_expr(node.args[0], tainted, producers):
        return node.lineno
    # builtin open(arg, mode) — only READ modes count (w/a/x/+ are writes)
    if isinstance(f, ast.Name) and f.id == "open" and node.args \
            and _is_state_expr(node.args[0], tainted, producers):
        mode = None
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                and isinstance(node.args[1].value, str):
            mode = node.args[1].value
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                mode = kw.value.value
        if mode is None or not re.search(r"[wax+]", mode):
            return node.lineno
    return None


def _ast_offenders(source: str) -> list[int]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    producers = _producers(tree)
    tainted = _tainted_vars(tree, producers)
    lines = {
        ln for node in ast.walk(tree) if isinstance(node, ast.Call)
        if (ln := _read_lineno(node, tainted, producers)) is not None
    }
    return sorted(lines)


# Files that legitimately touch state paths: export WRITERS and one-time
# migration/import bridges. These are not "reads as source of truth".
_ALLOWLIST = {
    "engine/state_writer.py",      # DB->YAML export writer
    "commands/handoff_write.py",   # handoff writer (write path)
    "engine/migrate_yaml.py",      # one-time YAML->DB migration import
    "commands/yaml_io.py",         # migration/import plumbing
    "commands/archive_yaml.py",    # archives YAML exports
    "engine/yaml_sync.py",         # inert no-op stubs
    "engine/pack.py",              # portable export/import tool (reads everything by design)
}

# All known violations resolved 2026-05-24 — ratchet is now clean.
# Adding a new violation to any scanned file will fail test_no_new_state_yaml_reads.
BASELINE: set[str] = set()

# Blind spots: violations the union scanner cannot reach. Document rather than
# pretend completeness. Each entry here must have a manual/behavioral guard.
_KNOWN_BLIND: set[str] = {
    "commands/inbox_dispatch.py",
    # _claim_next_item YAML else-branch calls subprocess(engine.inbox next_pending),
    # undetectable by static AST analysis. Guard applied 2026-05-24: --to is now
    # required in sqlite_only mode, so the else branch is never reached at runtime.
    # The dead else-branch code still exists in source; scanner cannot see it.
}


def _scan_offenders() -> dict[str, list[int]]:
    """Union of regex (direct idioms) and AST taint (indirection) detections."""
    offenders: dict[str, list[int]] = {}
    for d in _SCAN_DIRS:
        base = _SRC / d
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            rel = str(path.relative_to(_SRC))
            if rel in _ALLOWLIST:
                continue
            source = path.read_text(errors="replace")
            lines = source.splitlines()
            hits = {
                i for i, ln in enumerate(lines, 1)
                if not _IGNORE.search(ln)
                and any(p.search(ln) for p in _VIOLATION_PATTERNS)
            }
            # Apply noqa suppression to AST hits too, so # noqa: state-read works uniformly.
            hits.update(
                i for i in _ast_offenders(source)
                if i <= len(lines) and not _IGNORE.search(lines[i - 1])
            )
            if hits:
                offenders[rel] = sorted(hits)
    return offenders


def test_no_new_state_yaml_reads() -> None:
    """No file outside the baseline may read state YAML as authoritative input."""
    offenders = _scan_offenders()
    new = {f: lines for f, lines in offenders.items() if f not in BASELINE}
    assert not new, (
        "New 'SQLite is source of truth' violation(s) — these files read state "
        "YAML directly instead of querying SQLite:\n"
        + "\n".join(f"  {f}: lines {lines}" for f, lines in sorted(new.items()))
        + "\nRoute reads through the DAOs / state_reader, or add an explicit "
        "'# noqa: state-read' with justification if it is genuinely config."
    )


def test_blind_spots_are_real_and_disjoint() -> None:
    """Honesty check: any declared blind spot must be genuinely undetected by
    the union scanner, and must not overlap the baseline."""
    offenders = _scan_offenders()
    overlap = _KNOWN_BLIND & BASELINE
    assert not overlap, f"file is both baselined and blind: {sorted(overlap)}"
    falsely_blind = sorted(f for f in _KNOWN_BLIND if f in offenders)
    assert not falsely_blind, (
        "These are listed as blind spots but the scanner DOES detect them — "
        f"move them to BASELINE: {falsely_blind}"
    )


def test_baseline_has_no_stale_entries() -> None:
    """Ratchet: a baselined file that no longer offends must be removed from
    BASELINE so the violation count provably only decreases."""
    offenders = _scan_offenders()
    stale = sorted(f for f in BASELINE if f not in offenders)
    assert not stale, (
        "These files are in BASELINE but no longer read state YAML — remove them "
        "from BASELINE in this test (the migration ratchet only moves down):\n"
        + "\n".join(f"  {f}" for f in stale)
    )
