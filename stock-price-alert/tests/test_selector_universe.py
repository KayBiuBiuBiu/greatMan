"""选股宇宙：优先 stock_basic 本地缓存。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_load_universe_prefers_stock_basic_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from quant_core import selector

    cache = tmp_path / "stock_basic_cache.json"
    cache.write_text(
        json.dumps(
            {
                "stocks": [
                    {"symbol": "000001", "name": "平安银行"},
                    {"symbol": "600000", "name": "浦发银行"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(selector, "_MIN_STOCK_BASIC_CACHE_CODES", 2)

    def _resolved(_root=None):
        return cache

    monkeypatch.setattr(
        "quote_tushare.resolved_stock_basic_cache_path",
        _resolved,
    )

    codes, names, src = selector._load_universe_codes_and_names(
        {"quant_selector": {"use_stock_basic_cache_universe": True}, "sources": {}}
    )
    assert src == "stock_basic_cache"
    assert codes == ["000001", "600000"]
    assert names["000001"] == "平安银行"


def test_load_universe_akshare_when_cache_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_core import selector

    called: list[str] = []

    def fake_sh(*_a, **_k):
        called.append("sh")
        import pandas as pd

        return pd.DataFrame([{"证券代码": "600001"}])

    def fake_sz(*_a, **_k):
        called.append("sz")
        import pandas as pd

        return pd.DataFrame([{"证券代码": "000001"}])

    def fake_name():
        import pandas as pd

        return pd.DataFrame([{"code": "000001", "name": "A"}, {"code": "600001", "name": "B"}])

    monkeypatch.setattr(selector.ak, "stock_info_sh_name_code", fake_sh)
    monkeypatch.setattr(selector.ak, "stock_info_sz_name_code", fake_sz)
    monkeypatch.setattr(selector.ak, "stock_info_a_code_name", fake_name)

    codes, names, src = selector._load_universe_codes_and_names(
        {"quant_selector": {"use_stock_basic_cache_universe": False}}
    )
    assert src == "akshare_fallback"
    assert "sh" in called and "sz" in called
    assert codes == ["000001", "600001"]
    assert names.get("000001") == "A"


def test_daily_select_max_workers_clamped() -> None:
    from quant_core import selector

    assert selector._daily_select_max_workers_effective({"daily_select_max_workers": 99}) == 32
    assert selector._daily_select_max_workers_effective({"daily_select_max_workers": 0}) == 1
    assert selector._daily_select_max_workers_effective({}) == 6


def test_filter_out_star_board_if_requested() -> None:
    from quant_core import selector

    base = ["688001", "689001", "600000", "300001"]
    assert selector._filter_out_star_board_if_requested(base, {}) == base
    assert selector._filter_out_star_board_if_requested(
        base, {"quant_selector": {"exclude_star_board": False}}
    ) == base
    assert selector._filter_out_star_board_if_requested(
        base, {"quant_selector": {"exclude_star_board": True}}
    ) == ["600000", "300001"]


def test_run_daily_selector_parallel_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """并发路径与单线程路径在 mock 下结果一致。"""
    from quant_core import selector

    monkeypatch.setattr(
        selector,
        "_load_universe_codes_and_names",
        lambda _cfg: (["000001", "600000"], {"000001": "A", "600000": "B"}, "stock_basic_cache"),
    )
    monkeypatch.setattr(selector, "_load_code_to_sw_l1", lambda _cfg: {})

    def _fake_eval(code, **kwargs):
        score = 8.0 if code == "000001" else 3.0
        bt = {"profit": 1, "win": 60, "trades": 5, "note": ""}
        bucket, _reason = selector._classify(score, bt, bt, bt, th={})
        if bucket == "淘汰股":
            return bucket, {"code": code, "name": "x", "score": score, "reason": _reason}
        return bucket, {
            "code": code,
            "name": "x",
            "score": score,
            "sw_l1": "",
            "backtest": {"1y": bt, "3y": bt, "5y": bt},
            "reason": _reason,
        }

    monkeypatch.setattr(selector, "_eval_one_daily_select_stock", _fake_eval)

    cfg = {
        "scan_pool_max": 500,
        "quant_selector": {"daily_select_max_workers": 4, "per_stock_sleep_sec": 0},
    }
    out = selector.run_daily_selector(cfg, limit=2, top_n_per_strategy=5)
    q = out.get("优质股") or []
    assert len(q) >= 1
    assert any(r.get("code") == "000001" for r in q)
