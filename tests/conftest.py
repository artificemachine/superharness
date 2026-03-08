from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
