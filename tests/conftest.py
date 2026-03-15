from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT, SCRIPTS_DIR

# Ensure shims (SUPERHARNESS_PYTHON shim pattern) always resolve to the interpreter
# running the test suite, even when individual tests restrict PATH to /usr/bin:/bin.
os.environ.setdefault("SUPERHARNESS_PYTHON", sys.executable)


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS_DIR
