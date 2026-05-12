"""
未来第 N 个交易日收涨概率（相对锚定日收盘）：标签 close[T+N] > close[T] → 1，否则 0。
N = FORWARD_UP_HORIZON_TRADING_DAYS（当前为 5）。特征与日 K enrich_ohlcv 对齐，与 ml_train_forward4 共用。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from kline_store import init_schema, open_store_connection
from ml_kline_features import enrich_ohlcv

FORWARD4_FEATURE_KEYS = ("ma5", "ma20", "ret1", "vol_ratio", "atr", "macd_hist")

FORWARD4_MODEL_KIND = "forward4_up_nb"

# 训练与推理共同的预测 horizon（交易日）；与 ml_train_forward4 写出 model["horizon_trading_days"] 须一致
FORWARD_UP_HORIZON_TRADING_DAYS = 5

_F4_MODEL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def resolve_kline_db_path(cfg: dict[str, Any], root: Path) -> Path:
    ks = cfg.get("kline_store") or {}
    rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def resolve_forward4_model_path(cfg: dict[str, Any], root: Path) -> Path:
    box = cfg.get("ml_forward4") or {}
    rel = str(box.get("model_path") or "data/ml_forward4_nb.json").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def load_forward4_model_cached(model_path: Path) -> dict[str, Any] | None:
    key = str(model_path)
    try:
        mt = model_path.stat().st_mtime
    except OSError:
        return None
    hit = _F4_MODEL_CACHE.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        blob = json.loads(model_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(blob, dict):
        return None
    if str(blob.get("model_kind") or "") != FORWARD4_MODEL_KIND:
        return None
    h = blob.get("horizon_trading_days")
    if h is not None and int(h) != FORWARD_UP_HORIZON_TRADING_DAYS:
        return None
    out = dict(blob)
    out["_model_json_path"] = str(Path(key).resolve())
    _F4_MODEL_CACHE[key] = (mt, out)
    return out


def _feature_dict_from_enriched_row(row: pd.Series) -> dict[str, float] | None:
    out: dict[str, float] = {}
    for k in FORWARD4_FEATURE_KEYS:
        v = row.get(k)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            return None
    return out


def read_ohlcv_asc(conn: sqlite3.Connection, secid: str) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT trade_date, open, high, low, close, volume
        FROM daily_klines
        WHERE secid = ?
        ORDER BY trade_date ASC
        """,
        (str(secid).strip(),),
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [dict(r) for r in rows],
        columns=["trade_date", "open", "high", "low", "close", "volume"],
    )


def iter_labeled_samples_secid(
    conn: sqlite3.Connection,
    secid: str,
    *,
    min_bars: int = 120,
) -> Iterator[tuple[dict[str, float], int]]:
    for fv, y, _ad in iter_labeled_samples_secid_with_anchor(
        conn, secid, min_bars=min_bars
    ):
        yield fv, y


def iter_labeled_samples_secid_with_anchor(
    conn: sqlite3.Connection,
    secid: str,
    *,
    min_bars: int = 120,
) -> Iterator[tuple[dict[str, float], int, str]]:
    """yield (features, y, anchor_trade_date YYYY-MM-DD)。"""
    df = read_ohlcv_asc(conn, secid)
    h = int(FORWARD_UP_HORIZON_TRADING_DAYS)
    if len(df) < min_bars + h:
        return
    enriched = enrich_ohlcv(df)
    n = len(enriched)
    for i in range(0, n - h):
        c0 = float(enriched["close"].iloc[i])
        ch = float(enriched["close"].iloc[i + h])
        y = 1 if ch > c0 else 0
        fd = _feature_dict_from_enriched_row(enriched.iloc[i])
        if fd is None:
            continue
        ad = str(enriched["trade_date"].iloc[i])[:10]
        yield fd, y, ad


def compute_forward4_features_from_ohlcv_df(
    df: pd.DataFrame,
    *,
    anchor_trade_date: str | None = None,
    min_rows: int = 80,
) -> dict[str, float] | None:
    """
    与训练一致：对单票 OHLCV DataFrame（含 date 或 trade_date）在锚定日及之前截断后 enrich，取最后一根特征。
    用于 quant 选股路径（load_df 无 open 亦可，enrich 不依赖 open）。
    """
    if df is None or df.empty:
        return None
    work = df.copy()
    if "trade_date" not in work.columns and "date" in work.columns:
        work = work.rename(columns={"date": "trade_date"})
    if "trade_date" not in work.columns:
        return None
    work["trade_date"] = work["trade_date"].astype(str).str[:10]
    ad = (anchor_trade_date or str(work["trade_date"].iloc[-1]))[:10]
    if len(ad) != 10:
        return None
    work = work[work["trade_date"] <= ad]
    if len(work) < int(min_rows):
        return None
    for col in ("high", "low", "close", "volume"):
        if col not in work.columns:
            return None
    enriched = enrich_ohlcv(work)
    if enriched.empty:
        return None
    return _feature_dict_from_enriched_row(enriched.iloc[-1])


def compute_forward4_features_for_secid(
    conn: sqlite3.Connection,
    secid: str,
    anchor_trade_date: str,
    *,
    min_rows: int = 80,
) -> dict[str, float] | None:
    """
    用 anchor 日及之前全部日 K，取 anchor 当日（<= 锚定日的最后一根）的 enrich 特征。
    """
    ad = str(anchor_trade_date or "").strip()[:10]
    if len(ad) != 10:
        return None
    rows = conn.execute(
        """
        SELECT trade_date, open, high, low, close, volume
        FROM daily_klines
        WHERE secid = ? AND trade_date <= ?
        ORDER BY trade_date ASC
        """,
        (str(secid).strip(), ad),
    ).fetchall()
    if len(rows) < min_rows:
        return None
    df = pd.DataFrame(
        [dict(r) for r in rows],
        columns=["trade_date", "open", "high", "low", "close", "volume"],
    )
    enriched = enrich_ohlcv(df)
    if enriched.empty:
        return None
    last_td = str(enriched["trade_date"].iloc[-1])[:10]
    if last_td != ad:
        # 库未同步到锚定日：用最后一根近似（与监控 sqlite 滞后一致）
        pass
    return _feature_dict_from_enriched_row(enriched.iloc[-1])


def predict_forward4_up_probability(
    model: dict[str, Any],
    feats: dict[str, float],
) -> float | None:
    """P(标签=1)；含可选概率校准与 NB+XGB 融合（见模型 JSON 字段）。"""
    from ml_forward4_prob_tools import blended_forward4_probability

    mp = model.get("_model_json_path")
    mpath = Path(str(mp)) if mp else None
    return blended_forward4_probability(model, feats, model_json_path=mpath)


def list_stock_secids(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute(
        """
        SELECT DISTINCT secid FROM daily_klines
        WHERE (secid LIKE '0.%' OR secid LIKE '1.%')
          AND secid NOT LIKE '%.SI'
        ORDER BY secid
        """
    )
    return [str(r[0]).strip() for r in cur.fetchall() if r and r[0]]
