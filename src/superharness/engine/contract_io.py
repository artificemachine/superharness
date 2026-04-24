"""Canonical contract read/write path.

All contract-mutating commands must use write_contract() from this module.
Pydantic validation runs when pydantic is available; degrades gracefully when
it is not (e.g. minimal CI environments that install only core deps).
"""
from __future__ import annotations

import logging
import os
import tempfile

import yaml

logger = logging.getLogger(__name__)


class ContractValidationError(RuntimeError):
    """Raised when write_contract() is given a document that fails schema validation."""


try:
    from ruamel.yaml import YAML as RuamelYAML
    _RT_AVAILABLE = True
except ImportError:
    _RT_AVAILABLE = False

# Break-glass escape: SUPERHARNESS_SCHEMA_ENFORCEMENT=warn → logs at CRITICAL but still writes.
_ENFORCEMENT = os.environ.get("SUPERHARNESS_SCHEMA_ENFORCEMENT", "strict")


def _validate(doc: object) -> None:
    """Validate doc against Contract schema. No-op if pydantic is unavailable."""
    try:
        from pydantic import ValidationError
        from superharness.engine.schemas import Contract
    except ImportError:
        logger.debug("pydantic not available — contract schema validation skipped")
        return

    try:
        Contract.model_validate(doc)
    except ValidationError as exc:
        errs = "\n".join(
            f"  {'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        )
        if _ENFORCEMENT == "warn":
            logger.critical(
                "SCHEMA ENFORCEMENT BYPASSED (SUPERHARNESS_SCHEMA_ENFORCEMENT=warn). "
                "Violations:\n%s", errs
            )
        else:
            raise ContractValidationError(
                f"Refusing to write contract: {len(exc.errors())} schema violation(s)\n{errs}"
            ) from exc


def write_contract(path: str, doc: object) -> None:
    _validate(doc)

    dir_ = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    fd, tmp = tempfile.mkstemp(prefix=base, suffix=".tmp", dir=dir_)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if _RT_AVAILABLE:
                rt = RuamelYAML()
                rt.preserve_quotes = True
                rt.default_flow_style = False
                rt.dump(doc, f)
            else:
                f.write(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


def read_contract(path: str) -> tuple[dict, list]:
    """Load contract YAML and return (doc, validation_errors).

    validation_errors is an empty list when pydantic is unavailable or schema is satisfied.
    """
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    errors: list = []
    try:
        from pydantic import ValidationError
        from superharness.engine.schemas import Contract
        try:
            Contract.model_validate(doc)
        except ValidationError as exc:
            errors = exc.errors()
    except ImportError:
        pass
    return doc, errors
