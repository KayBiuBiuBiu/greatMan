"""config_startup_check 基础用例。"""

from __future__ import annotations

from pathlib import Path

from config_startup_check import run_startup_config_checks

_TESTS_ROOT = Path(__file__).resolve().parents[1]


def test_startup_check_example_config_no_fatal(merged_cfg: dict):
    errs, warns = run_startup_config_checks(merged_cfg, root=_TESTS_ROOT)
    assert errs == []
    assert isinstance(warns, list)
