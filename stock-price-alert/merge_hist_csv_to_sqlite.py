#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将 data/historical 下按股保存的 CSV 合并为单张 SQLite 表，便于训练与特征工程。"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _norm_col(name: str) -> str:
    return str(name).strip().lower().replace(" ", "")


def stem_to_code6(stem: str) -> str | None:
    """从 CSV 文件名得到 6 位 code，支持 600000 / sh.600000 / sz.000001。"""
    s = str(stem).strip()
    if s.isdigit() and len(s) <= 6:
        return s.zfill(6)
    low = s.lower()
    for p in ("sh.", "sz.", "bj."):
        if low.startswith(p):
            tail = s[len(p) :].strip()
            if tail.isdigit() and len(tail) <= 6:
                return tail.zfill(6)
    return None


def normalize_ohlcv(df, code: str) -> "object":
    import pandas as pd

    if df is None or df.empty:
        return None
    colmap = {_norm_col(c): c for c in df.columns}
    pick = {}

    def one(*keys: str) -> object:
        for k in keys:
            nk = _norm_col(k)
            if nk in colmap:
                return df[colmap[nk]]
        return None

    td = one("trade_date", "date", "日期")
    if td is None:
        return None
    pick["code"] = str(code).zfill(6)
    pick["trade_date"] = pd.to_datetime(td, errors="coerce").dt.strftime("%Y-%m-%d")
    for dst, keys in (
        ("open", ("open", "开盘")),
        ("high", ("high", "最高")),
        ("low", ("low", "最低")),
        ("close", ("close", "收盘")),
        ("volume", ("volume", "成交量")),
        ("amount", ("amount", "成交额")),
    ):
        s = one(*keys)
        pick[dst] = pd.to_numeric(s, errors="coerce") if s is not None else None

    out = pd.DataFrame(pick)
    out = out.dropna(subset=["trade_date"])
    # 去掉非法行
    out = out[out["trade_date"].str.len() == 10]
    extra_cols = [
        c
        for c in df.columns
        if _norm_col(c)
        not in {
            _norm_col(x)
            for x in (
                "trade_date",
                "date",
                "日期",
                "open",
                "开盘",
                "high",
                "最高",
                "low",
                "最低",
                "close",
                "收盘",
                "volume",
                "成交量",
                "amount",
                "成交额",
                "股票代码",
                "code",
            )
        }
    ]
    if extra_cols:
        out["extra_json"] = df[extra_cols].apply(
            lambda row: json.dumps(row.to_dict(), ensure_ascii=False),
            axis=1,
        )
    else:
        out["extra_json"] = None
    return out


def main() -> int:
    import pandas as pd

    ap = argparse.ArgumentParser(description="合并 historical CSV 到单表 SQLite")
    ap.add_argument(
        "--csv-dir",
        type=Path,
        default=ROOT / "data" / "historical",
        help="CSV 目录，默认 data/historical",
    )
    ap.add_argument(
        "--db-path",
        type=Path,
        default=ROOT / "data" / "hist_merged.db",
        help="输出 SQLite 路径，默认 data/hist_merged.db",
    )
    ap.add_argument(
        "--table",
        type=str,
        default="hist_daily_merged",
        help="表名，默认 hist_daily_merged（勿与 kline_store 的 daily_klines 混用）",
    )
    ap.add_argument(
        "--replace",
        action="store_true",
        help="导入前 DROP TABLE 清空该表",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多处理 N 个 CSV（0 为不限制）",
    )
    args = ap.parse_args()

    tbl = str(args.table).strip() or "hist_daily_merged"
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", tbl):
        print("表名只允许字母数字下划线且不能以数字开头", file=sys.stderr)
        return 1

    csv_dir = args.csv_dir.resolve()
    if not csv_dir.is_dir():
        print(f"目录不存在: {csv_dir}", file=sys.stderr)
        return 1

    db_path = args.db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        if args.replace:
            conn.execute(f'DROP TABLE IF EXISTS "{tbl}"')
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{tbl}" (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                extra_json TEXT,
                PRIMARY KEY (code, trade_date)
            )
            """
        )
        files = sorted(csv_dir.glob("*.csv"))
        if args.limit and args.limit > 0:
            files = files[: int(args.limit)]
        n_ok = 0
        n_skip = 0
        for fp in files:
            code6 = stem_to_code6(fp.stem)
            if code6 is None:
                n_skip += 1
                continue
            try:
                df0 = pd.read_csv(fp)
            except Exception as e:
                print(f"[skip] {fp.name}: {e}", file=sys.stderr)
                n_skip += 1
                continue
            m = normalize_ohlcv(df0, code6)
            if m is None or m.empty:
                n_skip += 1
                continue
            conn.execute(f'DELETE FROM "{tbl}" WHERE code = ?', (code6,))
            m.to_sql(
                tbl,
                conn,
                if_exists="append",
                index=False,
                method="multi",
            )
            n_ok += 1
            if n_ok % 100 == 0:
                print(f"…已合并 {n_ok} 个文件")
        conn.commit()
        print(f"完成：写入 {n_ok} 个标的 CSV，跳过 {n_skip}，库 {db_path} 表 {tbl}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
