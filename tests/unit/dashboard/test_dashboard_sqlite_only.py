"""RED tests for Step 2: dashboard dead YAML fallback branch removal.

Verifies that contract/inbox YAML reads are removed from dashboard-ui.py functions
that should use state_reader (SQLite) exclusively.
"""

import re
from pathlib import Path


# ── static regex check: no yaml.safe_load for contract/inbox ──────────────────

def _dashboard_source_lines() -> list[str]:
    """Read dashboard-ui.py source lines."""
    from pathlib import Path
    # Find the dashboard-ui.py file relative to the package
    import superharness
    pkg_dir = Path(superharness.__file__).parent
    dashboard_path = pkg_dir / "scripts" / "dashboard-ui.py"
    return dashboard_path.read_text().splitlines()


def test_no_yaml_safe_load_in_contract_owners():
    """contract_owners() must not have YAML safe_load fallback for contract.yaml."""
    lines = _dashboard_source_lines()
    # Find the contract_owners function range
    in_func = False
    indent = 0
    for i, line in enumerate(lines, start=1):
        if "def contract_owners(" in line:
            in_func = True
            indent = len(line) - len(line.lstrip())
            continue
        if in_func:
            cur_indent = len(line) - len(line.lstrip()) if line.strip() else indent + 1
            if cur_indent <= indent and line.strip():
                break  # function ended
            if "yaml.safe_load" in line and "contract" in line.lower():
                assert False, f"contract_owners() still reads YAML at line {i}: {line.strip()}"


def test_no_yaml_safe_load_in_contract_id():
    """contract_id() must not use yaml.safe_load for contract.yaml."""
    lines = _dashboard_source_lines()
    in_func = False
    indent = 0
    for i, line in enumerate(lines, start=1):
        if "def contract_id(" in line:
            in_func = True
            indent = len(line) - len(line.lstrip())
            continue
        if in_func:
            cur_indent = len(line) - len(line.lstrip()) if line.strip() else indent + 1
            if cur_indent <= indent and line.strip():
                break
            if "yaml.safe_load" in line:
                assert False, f"contract_id() still reads YAML at line {i}: {line.strip()}"


def test_no_yaml_safe_load_in_contract_tasks():
    """contract_tasks() must not have YAML safe_load fallback for contract.yaml."""
    lines = _dashboard_source_lines()
    in_func = False
    indent = 0
    for i, line in enumerate(lines, start=1):
        if "def contract_tasks(" in line:
            in_func = True
            indent = len(line) - len(line.lstrip())
            continue
        if in_func:
            cur_indent = len(line) - len(line.lstrip()) if line.strip() else indent + 1
            if cur_indent <= indent and line.strip():
                break
            if "yaml.safe_load" in line:
                assert False, f"contract_tasks() still reads YAML at line {i}: {line.strip()}"


def test_no_yaml_safe_load_in_plan_proposed_rows():
    """plan_proposed_rows() must not have YAML safe_load fallback for contract.yaml."""
    lines = _dashboard_source_lines()
    in_func = False
    indent = 0
    for i, line in enumerate(lines, start=1):
        if "def plan_proposed_rows(" in line:
            in_func = True
            indent = len(line) - len(line.lstrip())
            continue
        if in_func:
            cur_indent = len(line) - len(line.lstrip()) if line.strip() else indent + 1
            if cur_indent <= indent and line.strip():
                break
            # Allow handoff YAML reads (looking for *.yaml in handoffs dir)
            if "yaml.safe_load" in line and "contract" in line.lower():
                assert False, f"plan_proposed_rows() still reads contract YAML at line {i}: {line.strip()}"


def test_no_yaml_safe_load_for_contract_in_inbox_items():
    """inbox_items() must not use yaml.safe_load for inbox.yaml.
    
    Note: This test is expected to FAIL until Step 3 is complete.
    """
    lines = _dashboard_source_lines()
    in_func = False
    indent = 0
    for i, line in enumerate(lines, start=1):
        if "def inbox_items(" in line:
            in_func = True
            indent = len(line) - len(line.lstrip())
            continue
        if in_func:
            cur_indent = len(line) - len(line.lstrip()) if line.strip() else indent + 1
            if cur_indent <= indent and line.strip():
                break
            if "yaml.safe_load" in line:
                assert False, f"inbox_items() still reads YAML at line {i}: {line.strip()}"


def test_no_yaml_safe_load_contract_fallback_in_column_view():
    """Dashboard contract-read functions must not have YAML fallback reads of contract.yaml.
    
    The only legitimate contract.yaml yaml.safe_load should be in _tasks_from_yaml()
    which is the non-harness-path fallback function.
    """
    lines = _dashboard_source_lines()
    # Track which function we're in to skip _tasks_from_yaml
    in_excluded_func = False
    excluded_indent = 0
    for i, line in enumerate(lines, start=1):
        # Track function boundaries
        if line.strip().startswith("def "):
            in_excluded_func = "def _tasks_from_yaml" in line
            excluded_indent = len(line) - len(line.lstrip()) if in_excluded_func else 0
            continue
        
        if in_excluded_func:
            cur_indent = len(line) - len(line.lstrip()) if line.strip() else excluded_indent + 1
            if cur_indent <= excluded_indent and line.strip():
                in_excluded_func = False
            continue  # skip lines inside _tasks_from_yaml
        
        if "yaml.safe_load" in line:
            context_start = max(0, i - 4)
            context = lines[context_start:i + 2]
            context_str = "\n".join(context)
            if "contract_file" in context_str or "contract." in context_str:
                assert False, (
                    f"YAML safe_load of contract data still present near line {i}:\n"
                    + "\n".join(f"  {j}: {lines[j-1]}" for j in range(context_start + 1, i + 2))
                )


def test_no_yaml_safe_load_review_queue():
    """review_queue() must not have yaml.safe_load fallback for contract.yaml."""
    lines = _dashboard_source_lines()
    in_func = False
    indent = 0
    for i, line in enumerate(lines, start=1):
        if "def review_queue(" in line:
            in_func = True
            indent = len(line) - len(line.lstrip())
            continue
        if in_func:
            cur_indent = len(line) - len(line.lstrip()) if line.strip() else indent + 1
            if cur_indent <= indent and line.strip():
                break
            if "yaml.safe_load" in line:
                assert False, f"review_queue() still reads YAML at line {i}: {line.strip()}"
