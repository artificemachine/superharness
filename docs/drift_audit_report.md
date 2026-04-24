# Contract Schema Drift Audit Report

**Date:** 2026-04-24
**Contract:** `.superharness/contract.yaml`
**Total tasks:** 94
**Schema:** `Contract` / `ContractTask` in `src/superharness/engine/schemas.py`
**Iteration:** 3 (produced before Iteration 4 data reconciliation)

---

## Summary

| Category | Affected tasks | Status |
|---|---|---|
| `AC_DICT` — `acceptance_criteria` item is a dict, not a string | 1 (task index 85) | Resolved in Iteration 4 |

All other 93 tasks pass `ContractTask.model_validate()` cleanly.
Contract-level fields (`id`, `created`, `created_by`, `status`) are present and valid.

---

## Detail

### AC_DICT — task 85: `feat.headless.auto-approve-policy`

**Field:** `acceptance_criteria[0]`
**Current value:** `{'support auto_approve_plans': 'true in policy/profile.yaml'}`
**Expected type:** `str`
**Fix:** Convert to string: `"support auto_approve_plans: true in policy/profile.yaml"`

**Root cause:** YAML dict-literal notation was used where a plain string was intended.
The criterion is `support auto_approve_plans: true in policy/profile.yaml` — a single
plain-text statement, not a key/value pair. The correct YAML form is a quoted string.

**Fix applied in:** Iteration 4

---

## What Was Checked

- Every `ContractTask` field validated against the Pydantic model
- Contract-level required fields (`id`, `created`, `created_by`, `status`)
- `TaskStatus` enum coverage (extended in Iteration 0 to include 4 previously missing values)

---

## Status After Iteration 4

This report should be updated to show all categories as resolved.
`tests/unit/test_contract_schema_compliance.py::test_live_contract_passes_full_validation`
must be green.
