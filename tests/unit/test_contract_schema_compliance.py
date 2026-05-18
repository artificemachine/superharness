"""Schema compliance test for the live contract.

Reads contract data from SQLite (the source of truth) via state_reader,
then validates the reconstructed document against the Contract schema.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from superharness.engine import state_reader
from superharness.engine.schemas import Contract


def test_live_contract_passes_full_validation():
    """Every task in the live contract must satisfy the Contract schema."""
    project_dir = str(Path(os.environ.get("SUPERHARNESS_PROJECT_DIR", ".")).resolve())
    doc = state_reader.get_contract_doc(project_dir)
    if not doc or not doc.get("tasks"):
        pytest.skip("No contract data in SQLite — skipping schema compliance check")
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
            f"{len(errors)} schema violation(s):\n{detail}"
        ) from exc
