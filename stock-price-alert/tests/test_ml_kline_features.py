# -*- coding: utf-8 -*-
import unittest
from datetime import date, timedelta

import pandas as pd

from ml_kline_features import (
    TREND_FEATURE_COLUMNS,
    add_forward_down_label,
    build_trend_frame_with_label,
    enrich_ohlcv,
)


class TestMlKlineFeatures(unittest.TestCase):
    def test_forward_label_last_rows_nan(self):
        rows = []
        base = 10.0
        for i in range(30):
            rows.append(
                {
                    "trade_date": f"2020-01-{i+1:02d}",
                    "open": base,
                    "high": base + 0.1,
                    "low": base - 0.1,
                    "close": base,
                    "volume": 1e6,
                }
            )
        df = pd.DataFrame(rows)
        tagged = add_forward_down_label(df, forward_days=5, threshold_pct=-3.0)
        self.assertTrue(pd.isna(tagged["label"].iloc[-1]))
        self.assertTrue(tagged["label"].iloc[: -5].notna().all())

    def test_enrich_has_columns(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2020-01-01", "2020-01-02", "2020-01-03"],
                "open": [1, 1, 1],
                "high": [1.1, 1.1, 1.1],
                "low": [0.9, 0.9, 0.9],
                "close": [1.0, 1.0, 1.0],
                "volume": [1e6, 1e6, 1e6],
            }
        )
        out = enrich_ohlcv(df)
        for c in ("ma5", "ma20", "ret1", "vol_ratio", "atr", "macd_hist"):
            self.assertIn(c, out.columns)

    def test_trend_frame_columns(self):
        rows = []
        d0 = date(2020, 1, 1)
        for i in range(70):
            p = 10.0 + i * 0.01
            rows.append(
                {
                    "trade_date": (d0 + timedelta(days=i)).isoformat(),
                    "open": p,
                    "high": p + 0.2,
                    "low": p - 0.2,
                    "close": p,
                    "volume": 1e6 + i * 100,
                }
            )
        df = pd.DataFrame(rows)
        out = build_trend_frame_with_label(df, forward_days=5, threshold_pct=-3.0)
        for c in TREND_FEATURE_COLUMNS:
            self.assertIn(c, out.columns)
        self.assertIn("label", out.columns)
        self.assertTrue(pd.isna(out["label"].iloc[-1]))


if __name__ == "__main__":
    unittest.main()
