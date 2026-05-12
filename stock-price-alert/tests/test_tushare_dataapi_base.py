"""Tushare DataApi 基址：避免默认 api.waditu.com 无法解析。"""

import os

import pytest


def test_quote_tushare_patches_default_dataapi_base() -> None:
    import tushare.pro.client as ts_client

    import quote_tushare as qt

    qt.configure_tushare_from_sources(None)
    assert ts_client.DataApi._DataApi__http_url == qt._DEFAULT_TUSHARE_DATAAPI_BASE
    assert qt._LEGACY_WADITU_DATAAPI_BASE in qt._DATAAPI_BASE_CHAIN


def test_pro_dataapi_base_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    import tushare.pro.client as ts_client

    import quote_tushare as qt

    monkeypatch.setenv("TUSHARE_PRO_DATAAPI_BASE", "https://example.test/dataapi")
    qt.configure_tushare_from_sources({"tushare": {"enabled": False}})
    assert ts_client.DataApi._DataApi__http_url == "https://example.test/dataapi"


def test_pro_dataapi_base_config_overrides_when_env_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tushare.pro.client as ts_client

    import quote_tushare as qt

    monkeypatch.delenv("TUSHARE_PRO_DATAAPI_BASE", raising=False)
    qt.configure_tushare_from_sources(
        {
            "tushare": {
                "enabled": False,
                "pro_dataapi_base": "https://cfg.example/dataapi",
            }
        }
    )
    assert ts_client.DataApi._DataApi__http_url == "https://cfg.example/dataapi"


def test_query_retries_transient_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    import requests
    import tushare.pro.client as ts_client

    import quote_tushare as qt

    qt.configure_tushare_from_sources({"tushare": {"enabled": False}})
    calls: list[str] = []

    class OkResp:
        status_code = 200
        text = json.dumps(
            {"code": 0, "data": {"fields": ["trade_date"], "items": [["20200101"]]}}
        )

        def __bool__(self) -> bool:
            return True

    def fake_post(url: str, json=None, timeout=None) -> object:
        calls.append(url)
        if len(calls) < 2:
            raise requests.exceptions.ConnectionError("simulated DNS")
        return OkResp()

    monkeypatch.setattr(requests, "post", fake_post)
    api = ts_client.DataApi(token="x", timeout=5)
    df = api.query("daily", ts_code="000001.SZ")
    assert not df.empty
    assert len(calls) >= 2
