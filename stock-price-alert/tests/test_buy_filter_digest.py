"""buy_filter_digest 路径与无数据正文。"""

from __future__ import annotations

import json
from pathlib import Path

from buy_filter_digest import build_friday_buy_filter_digest, resolve_alert_jsonl_path


def test_resolve_jsonl_none_when_logging_off(tmp_path: Path) -> None:
    cfg = {"logging": {"enabled": False, "file": "logs/run_alert.jsonl"}}
    assert resolve_alert_jsonl_path(cfg, tmp_path) is None


def test_build_digest_logging_off(tmp_path: Path) -> None:
    cfg = {"logging": {"enabled": False}}
    subj, body = build_friday_buy_filter_digest(
        cfg, tmp_path, forward_days=5, max_events=10
    )
    assert "复盘" in subj
    assert "logging.enabled" in body


def test_build_digest_empty_events(tmp_path: Path) -> None:
    logf = tmp_path / "logs" / "a.jsonl"
    logf.parent.mkdir(parents=True)
    logf.write_text("", encoding="utf-8")
    cfg = {"logging": {"enabled": True, "file": str(logf.relative_to(tmp_path))}}
    subj, body = build_friday_buy_filter_digest(
        cfg, tmp_path, forward_days=5, max_events=10
    )
    assert "watch_strategy_buy_filtered" in body
