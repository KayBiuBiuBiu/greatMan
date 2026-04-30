"""pytest 根路径与共享 fixture。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_TESTS = ROOT / "tests"
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))


@pytest.fixture
def merged_cfg() -> dict:
    from run_alert import merge_full_config

    ex = ROOT / "config.example.json"
    return merge_full_config(json.loads(ex.read_text(encoding="utf-8")))


@pytest.fixture(autouse=True)
def _clear_sector_round_cache():
    from sector_em import clear_round_cache

    clear_round_cache()
    yield
    clear_round_cache()
