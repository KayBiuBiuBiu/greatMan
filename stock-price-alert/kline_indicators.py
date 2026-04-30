"""日 K 指标预计算：MA / 高宽箱体 / ATR% / MACD(dif,dea,hist) 序列，写入 indicator_last 表。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from quote_eastmoney import kline_dict_from_ohlcv_series
from trend_slippage_risk import _atr_close_pct, _macd_components


def upsert_indicator_last(
    conn: sqlite3.Connection,
    secid: str,
    *,
    trade_date: str,
    ma5: float,
    ma20: float,
    ma60: float | None,
    high20: float,
    low20: float,
    atr_pct: float | None,
    macd_bundle: dict[str, Any],
    computed_iso: str,
) -> None:
    conn.execute(
        """
        INSERT INTO indicator_last(
            secid, trade_date, ma5, ma20, ma60, high20, low20,
            atr_pct, macd_bundle_json, computed_iso
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(secid) DO UPDATE SET
            trade_date=excluded.trade_date,
            ma5=excluded.ma5,
            ma20=excluded.ma20,
            ma60=excluded.ma60,
            high20=excluded.high20,
            low20=excluded.low20,
            atr_pct=excluded.atr_pct,
            macd_bundle_json=excluded.macd_bundle_json,
            computed_iso=excluded.computed_iso
        """,
        (
            str(secid).strip(),
            trade_date[:10],
            float(ma5),
            float(ma20),
            float(ma60) if ma60 is not None else None,
            float(high20),
            float(low20),
            float(atr_pct) if atr_pct is not None else None,
            json.dumps(macd_bundle, ensure_ascii=False),
            computed_iso,
        ),
    )
    conn.commit()


def read_indicator_last(
    conn: sqlite3.Connection, secid: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM indicator_last WHERE secid = ?",
        (str(secid).strip(),),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    raw = d.get("macd_bundle_json")
    if isinstance(raw, str) and raw.strip():
        try:
            d["macd_bundle"] = json.loads(raw)
        except json.JSONDecodeError:
            d["macd_bundle"] = None
    else:
        d["macd_bundle"] = None
    return d


def compute_macd_bundle(closes: list[float]) -> dict[str, list[float]]:
    dif, dea, hist = _macd_components(closes)
    if not hist:
        return {"dif": [], "dea": [], "hist": []}
    tail = 40
    return {
        "dif": [float(x) for x in dif[-tail:]],
        "dea": [float(x) for x in dea[-tail:]],
        "hist": [float(x) for x in hist[-tail:]],
    }


def compute_and_store_indicator_last_for_secid(
    conn: sqlite3.Connection,
    secid: str,
    *,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    vols: list[float],
    last_trade_date: str | None,
) -> bool:
    """由已排序 OHLCV（与 read_ohlcv_lists 一致）写一条 indicator_last。"""
    if len(closes) < 35 or not last_trade_date:
        return False
    kd = kline_dict_from_ohlcv_series(
        opens,
        highs,
        lows,
        closes,
        vols,
        return_closes=True,
        kline_data_source="sqlite",
        kline_last_trade_date=last_trade_date,
    )
    if not kd:
        return False
    atr = _atr_close_pct(closes, kd, 20, method="wilder")
    bundle = compute_macd_bundle(closes)
    upsert_indicator_last(
        conn,
        secid,
        trade_date=str(last_trade_date)[:10],
        ma5=float(kd["ma5"]),
        ma20=float(kd["ma20"]),
        ma60=float(kd["ma60"]) if kd.get("ma60") is not None else None,
        high20=float(kd["high20"]),
        low20=float(kd["low20"]),
        atr_pct=float(atr) if atr is not None else None,
        macd_bundle=bundle,
        computed_iso=datetime.now().isoformat(timespec="seconds"),
    )
    return True


def merge_indicator_last_into_kline(
    out: dict[str, Any], snap: dict[str, Any] | None
) -> dict[str, Any]:
    """若 trade_date 对齐，将预计算 MACD 序列挂到 kline 供趋势模块短路。"""
    if not snap or not isinstance(out, dict):
        return out
    td = str(snap.get("trade_date") or "")[:10]
    od = str(out.get("kline_last_trade_date") or "")[:10]
    if not td or td != od:
        return out
    b = snap.get("macd_bundle")
    if isinstance(b, dict):
        dif = b.get("dif") or []
        dea = b.get("dea") or []
        hist = b.get("hist") or []
        if isinstance(dif, list) and isinstance(dea, list) and isinstance(hist, list):
            if len(hist) >= 4 and len(dif) >= 3 and len(dea) >= 3:
                out["precomputed_macd"] = {
                    "dif": [float(x) for x in dif],
                    "dea": [float(x) for x in dea],
                    "hist": [float(x) for x in hist],
                }
    ap = snap.get("atr_pct")
    if ap is not None:
        try:
            out["precomputed_atr_pct"] = float(ap)
        except (TypeError, ValueError):
            pass
    return out
