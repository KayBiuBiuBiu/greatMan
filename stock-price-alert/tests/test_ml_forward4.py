"""ml_forward4 标签与推理烟测。"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from kline_store import init_schema, open_store_connection, upsert_bars
import pandas as pd

from ml_forward4 import (
    FORWARD4_MODEL_KIND,
    compute_forward4_features_for_secid,
    compute_forward4_features_from_ohlcv_df,
    iter_labeled_samples_secid,
    predict_forward4_up_probability,
)
from ml_train import fit_gaussian_nb


def _seed_up_trend_db(path: Path, *, n: int = 160) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_store_connection(path)
    try:
        init_schema(conn)
        rows = []
        t0 = date(2024, 1, 2)
        for i in range(n):
            d = (t0 + timedelta(days=i)).isoformat()
            c = 10.0 + math.sin(i / 4.0) * 0.8 + i * 0.015
            rows.append((d, c, c + 0.1, c - 0.1, c, 1e6 + i))
        upsert_bars(conn, "0.000001", rows)
    finally:
        conn.close()


@pytest.fixture()
def tmp_kline_db(tmp_path: Path) -> Path:
    p = tmp_path / "t.db"
    _seed_up_trend_db(p, n=160)
    return p


def test_iter_samples_and_predict(tmp_kline_db: Path) -> None:
    conn = open_store_connection(tmp_kline_db)
    try:
        init_schema(conn)
        xs: list[dict[str, float]] = []
        ys: list[int] = []
        for fv, y in iter_labeled_samples_secid(conn, "0.000001", min_bars=80):
            xs.append(fv)
            ys.append(y)
        assert len(xs) >= 50
        assert len(set(ys)) == 2
        model = fit_gaussian_nb(xs, ys)
        model["model_kind"] = FORWARD4_MODEL_KIND
        last_d = (date(2024, 1, 2) + timedelta(days=159)).isoformat()
        feats = compute_forward4_features_for_secid(
            conn, "0.000001", last_d, min_rows=80
        )
        assert feats is not None
        p = predict_forward4_up_probability(model, feats)
        assert p is not None
        assert 0.0 <= p <= 1.0
    finally:
        conn.close()


def test_features_from_date_column_df(tmp_kline_db: Path) -> None:
    conn = open_store_connection(tmp_kline_db)
    try:
        init_schema(conn)
        rows = conn.execute(
            """
            SELECT trade_date, open, high, low, close, volume FROM daily_klines
            WHERE secid='0.000001' ORDER BY trade_date ASC
            """
        ).fetchall()
    finally:
        conn.close()
    df = pd.DataFrame([dict(r) for r in rows]).rename(columns={"trade_date": "date"})
    f = compute_forward4_features_from_ohlcv_df(df, min_rows=80)
    assert f is not None
    assert "ma20" in f


def test_model_json_roundtrip(tmp_kline_db: Path, tmp_path: Path) -> None:
    conn = open_store_connection(tmp_kline_db)
    try:
        init_schema(conn)
        samples = list(iter_labeled_samples_secid(conn, "0.000001", min_bars=80))
        xs = [a for a, _ in samples]
        ys = [b for _, b in samples]
        model = fit_gaussian_nb(xs, ys)
        model["model_kind"] = FORWARD4_MODEL_KIND
    finally:
        conn.close()
    out = tmp_path / "m.json"
    out.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    blob = json.loads(out.read_text(encoding="utf-8"))
    assert blob.get("model_kind") == FORWARD4_MODEL_KIND
