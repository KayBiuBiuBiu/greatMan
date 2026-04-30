"""responses 模拟东财 stock/get 的 f127（可选链路的 smoke）。"""

from __future__ import annotations

import re

import pytest
import responses

from sector_em import fetch_stock_industry_f127


@pytest.fixture
def cfg_em_host(tmp_path, merged_cfg: dict) -> dict:
    import copy

    cfg = copy.deepcopy(merged_cfg)
    cfg["sector_em"] = dict(cfg.get("sector_em") or {})
    cfg["sector_em"]["api_hosts"] = ["https://push2.example.test"]
    return cfg


@responses.activate
def test_fetch_f127_from_mocked_host(cfg_em_host: dict) -> None:
    responses.add(
        responses.GET,
        re.compile(r"https://push2\.example\.test/api/qt/stock/get"),
        json={"data": {"f127": "能源金属"}},
        status=200,
    )
    name = fetch_stock_industry_f127("600711", "sh", cfg_em_host)
    assert name == "能源金属"
