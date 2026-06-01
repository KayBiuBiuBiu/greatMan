"""Tushare Pro API 基址：避免默认 api.waditu.com 无法解析。"""

import os

import pytest


def test_quote_tushare_patches_default_dataapi_base() -> None:
    import tushare.pro.client as ts_client

    import quote_tushare as qt

    qt.configure_tushare_from_sources(None)
    assert ts_client.DataApi._DataApi__http_url == qt._DEFAULT_TUSHARE_DATAAPI_BASE
    assert qt._TUSHARE_DATAAPI_COMPAT_BASE in qt._DATAAPI_BASE_CHAIN
    assert qt._LEGACY_WADITU_DATAAPI_BASE in qt._DATAAPI_BASE_CHAIN


def test_pro_dataapi_base_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    import tushare.pro.client as ts_client

    import quote_tushare as qt

    monkeypatch.setenv("TUSHARE_PRO_DATAAPI_BASE", "https://example.test")
    qt.configure_tushare_from_sources({"tushare": {"enabled": False}})
    assert ts_client.DataApi._DataApi__http_url == "https://example.test"


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
                "pro_dataapi_base": "https://cfg.example",
            }
        }
    )
    assert ts_client.DataApi._DataApi__http_url == "https://cfg.example"


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


def test_tushare_post_url_supports_official_and_dataapi_base() -> None:
    import quote_tushare as qt

    assert qt._tushare_post_url("https://api.tushare.pro", "daily") == "https://api.tushare.pro"
    assert (
        qt._tushare_post_url("https://api.tushare.pro/dataapi", "daily")
        == "https://api.tushare.pro/dataapi/daily"
    )


def test_sw_daily_uses_bulk_query_when_dynamic_method_missing() -> None:
    import pandas as pd

    import quote_tushare as qt
    qt._reset_sw_daily_bulk_cache()
    old_bulk = qt._CFG.get("sw_daily_bulk_enabled", False)
    qt._CFG["sw_daily_bulk_enabled"] = True

    class FakePro:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None, str, str]] = []

        def query(self, api_name: str, **kwargs) -> pd.DataFrame:
            self.calls.append(
                (
                    api_name,
                    kwargs.get("ts_code"),
                    str(kwargs.get("start_date")),
                    str(kwargs.get("end_date")),
                )
            )
            if api_name == "sw_daily":
                return pd.DataFrame(
                    [
                        {
                            "ts_code": "801010.SI",
                            "trade_date": "20260525",
                            "open": 1,
                            "high": 2,
                            "low": 0.5,
                            "close": 1.5,
                            "vol": 100,
                        }
                    ]
                )
            return pd.DataFrame()

    fake = FakePro()
    df = qt._fetch_sw_level1_daily_df(fake, "801010.SI", "20260501", "20260525")
    df2 = qt._fetch_sw_level1_daily_df(fake, "801020.SI", "20260501", "20260525")

    assert df is not None
    assert not df.empty
    assert df2 is None
    assert fake.calls == [("sw_daily", None, "20260501", "20260525")]
    qt._CFG["sw_daily_bulk_enabled"] = old_bulk
    qt._reset_sw_daily_bulk_cache()
