"""Schema compliance test for the live contract (Iteration 3).

This test is the canonical RED for Iterations 3-5.
It MUST fail until all data drift is reconciled in Iteration 4.
It MUST pass after Iteration 4 completes — and must stay green from there on.

Do NOT skip or xfail this test. Let it fail as a visible signal that
data reconciliation work remains open.
"""
from __future__ import annotations

import yaml
from pydantic import ValidationError

from superharness.engine.schemas import Contract


def test_live_contract_passes_full_validation():
    """Every task in the live contract must satisfy the Contract schema."""
    with open(".superharness/contract.yaml", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    try:
        Contract.model_validate(doc)
    except ValidationError as exc:
        errors = exc.errors()
        detail = "\n".join(
            f"  tasks[{e['loc'][1]}].{'.'.join(str(x) for x in e['loc'][2:])}: {e['msg']}"
            if len(e["loc"]) > 2 else f"  {'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
            for e in errors
        )
        raise AssertionError(
            f"{len(errors)} schema violation(s) — run Iteration 4 data reconciliation:\n{detail}"
        ) from exc
