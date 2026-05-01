#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量下载 A 股日 K 到本地 CSV。

- 列表来源：
  - `baostock-all`：`baostock.query_all_stock(day=…)` 全市场（**需 `--provider baostock`**，最稳）；
  - `auto` / `info` / `spot`：AKShare 列表；
  - `db`：本地 `daily_klines.db` 已同步个股（适合训练补数）。
- 行情来源：`--provider akshare`（默认）或 `baostock`。
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_STOCK_SECID = re.compile(r"^[01]\.(\d{6})$")
_BS_A_CODE = re.compile(r"^(sh|sz)\.\d{6}$")


def _ymd_to_yyyy_mm_dd(s: str) -> str:
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _code_to_baostock_symbol(code6: str) -> str:
    """A 股常见规则：6 开头上交所，其余深交所（含 000/001/002/300）。"""
    c = code6.zfill(6)
    if c.startswith("6"):
        return f"sh.{c}"
    return f"sz.{c}"


def _list_codes_from_sqlite(db_path: Path) -> list[str]:
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLite 不存在: {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT DISTINCT secid FROM daily_klines ORDER BY secid"
        ).fetchall()
    finally:
        conn.close()
    out: list[str] = []
    for (sid,) in rows:
        s = str(sid or "").strip()
        m = _STOCK_SECID.match(s)
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def _list_akshare_info() -> list[str]:
    import akshare as ak  # type: ignore[import-not-found]

    df = ak.stock_info_a_code_name()
    col = None
    for c in ("code", "证券代码", "CODE", "symbol"):
        if c in df.columns:
            col = c
            break
    if col is None:
        raise KeyError(f"stock_info_a_code_name 无代码列，实际列: {list(df.columns)}")
    s = df[col].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    codes = [c.zfill(6) for c in s if c.isdigit() and len(c.zfill(6)) == 6]
    return sorted(set(codes))


def _list_akshare_spot() -> list[str]:
    import akshare as ak  # type: ignore[import-not-found]

    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            df = ak.stock_zh_a_spot_em()
            s = df["代码"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
            codes = [c.zfill(6) for c in s if c.isdigit() and len(c.zfill(6)) == 6]
            return sorted(set(codes))
        except Exception as e:
            last = e
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"stock_zh_a_spot_em 失败（已重试 3 次）: {last}") from last


def _list_baostock_all(bs: Any, day_hint: str | None) -> list[str]:
    """query_all_stock：返回 sh./sz. 六位代码标的（过滤指数等非常见形态）。"""
    days: list[str] = []
    if day_hint and str(day_hint).strip():
        days.append(str(day_hint).strip()[:10])
    for i in range(12):
        d = (datetime.now().date() - timedelta(days=i)).strftime("%Y-%m-%d")
        if d not in days:
            days.append(d)
    last_err: str | None = None
    for d in days:
        rs = bs.query_all_stock(day=d)
        if rs.error_code != "0":
            last_err = str(rs.error_msg)
            continue
        out: list[str] = []
        while rs.next():
            row = rs.get_row_data()
            if not row:
                continue
            sym = str(row[0]).strip().lower()
            if _BS_A_CODE.match(sym):
                out.append(sym)
        if out:
            print(f"[列表] baostock query_all_stock 使用交易日 {d}，共 {len(out)} 条", file=sys.stderr)
            return sorted(set(out))
    raise RuntimeError(f"baostock query_all_stock 无数据: {last_err or 'unknown'}")


def _resolve_codes(
    list_source: str,
    sqlite_path: Path | None,
    *,
    bs_mod: Any | None = None,
    baostock_list_day: str | None = None,
) -> list[str]:
    src = (list_source or "auto").strip().lower()
    if src == "baostock-all":
        if bs_mod is None:
            raise SystemExit("--list-source baostock-all 需要先登录 baostock（请使用 --provider baostock）")
        return _list_baostock_all(bs_mod, baostock_list_day)
    if src == "db":
        if sqlite_path is None or not str(sqlite_path).strip():
            raise SystemExit("--list-source db 时必须指定 --sqlite PATH")
        return _list_codes_from_sqlite(sqlite_path)
    if src == "info":
        return _list_akshare_info()
    if src == "spot":
        return _list_akshare_spot()
    # auto
    try:
        return _list_akshare_info()
    except Exception as e1:
        print(f"[列表] stock_info_a_code_name 不可用，改用 spot：{e1}", file=sys.stderr)
        return _list_akshare_spot()


def _ak_adjust_to_bs_flag(adjust: str) -> str:
    a = (adjust or "").strip().lower()
    if a == "qfq":
        return "2"
    if a == "hfq":
        return "3"
    return "1"


def _download_one_akshare(
    ak: Any,
    code: str,
    *,
    start_date: str,
    end_date: str,
    adjust: str,
    out_path: Path,
) -> bool:
    df = ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=str(start_date).strip(),
        end_date=str(end_date).strip(),
        adjust=str(adjust or "").strip(),
    )
    if df is None or df.empty:
        return False
    df.to_csv(out_path, encoding="utf-8-sig", index=False)
    return True


def _download_one_baostock(
    bs: Any,
    code_or_sym: str,
    *,
    start_yyyy_mm_dd: str,
    end_yyyy_mm_dd: str,
    adjustflag: str,
    out_path: Path,
) -> bool:
    s = str(code_or_sym).strip().lower()
    if "." in s and _BS_A_CODE.match(s):
        sym = s
    else:
        sym = _code_to_baostock_symbol(s)
    rs = bs.query_history_k_data_plus(
        sym,
        "date,open,high,low,close,volume,amount,turn,pctChg",
        start_date=start_yyyy_mm_dd,
        end_date=end_yyyy_mm_dd,
        frequency="d",
        adjustflag=adjustflag,
    )
    rows: list[list[str]] = []
    if rs.error_code != "0":
        raise RuntimeError(rs.error_msg)
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return False
    import pandas as pd

    df = pd.DataFrame(rows, columns=rs.fields)
    df.to_csv(out_path, encoding="utf-8-sig", index=False)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="批量下载 A 股日 K（AKShare / Baostock，列表可来自本地库）"
    )
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "data" / "historical",
        help="输出目录，默认 data/historical",
    )
    ap.add_argument(
        "--list-source",
        type=str,
        choices=("auto", "info", "spot", "db", "baostock-all"),
        default="auto",
        help="股票列表：baostock-all 全市场(须 baostock)；db 本地库；auto/info/spot 为 AKShare",
    )
    ap.add_argument(
        "--baostock-list-day",
        type=str,
        default="",
        help="query_all_stock 的交易日 YYYY-MM-DD，空则自动从最近日期回退尝试",
    )
    ap.add_argument(
        "--sqlite",
        type=Path,
        default=None,
        help="daily_klines.db 路径；--list-source db 时必填，auto/info/spot 时可省略",
    )
    ap.add_argument(
        "--provider",
        type=str,
        choices=("akshare", "baostock"),
        default="akshare",
        help="K 线数据源：akshare（默认）或 baostock（东财限流时可试）",
    )
    ap.add_argument("--start-date", type=str, default="20180101", help="开始 YYYYMMDD")
    ap.add_argument(
        "--end-date",
        type=str,
        default="",
        help="结束 YYYYMMDD，默认今天",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.8,
        help="每只股票间隔（秒），全量建议 1~2 降低被拒概率",
    )
    ap.add_argument(
        "--adjust",
        type=str,
        default="qfq",
        choices=("qfq", "hfq", ""),
        help="复权：qfq 前复权 / hfq 后复权 / 空不复权",
    )
    ap.add_argument("--limit", type=int, default=0, help="仅前 N 只，0 为不截断")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="CSV 已存在且非空则跳过",
    )
    args = ap.parse_args()

    if args.list_source == "baostock-all" and args.provider != "baostock":
        raise SystemExit("--list-source baostock-all 必须与 --provider baostock 同时使用")

    end = (args.end_date or "").strip() or datetime.now().strftime("%Y%m%d")
    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    sqlite_path = args.sqlite
    if args.list_source == "db" and sqlite_path is None:
        cand = ROOT / "data" / "daily_klines.db"
        if cand.is_file():
            sqlite_path = cand
        else:
            raise SystemExit("--list-source db 需要 --sqlite，且未找到默认 data/daily_klines.db")

    print(f"列表来源: {args.list_source}" + (f"  db={sqlite_path}" if sqlite_path else ""))

    bs_mod: Any = None
    if args.provider == "baostock" or args.list_source == "baostock-all":
        try:
            import baostock as bs_mod  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SystemExit("请先安装 baostock：pip install baostock") from exc
        lg = bs_mod.login()
        if lg.error_code != "0":
            raise SystemExit(f"baostock 登录失败: {lg.error_msg}")

    bday = (args.baostock_list_day or "").strip() or None
    codes = _resolve_codes(
        args.list_source,
        sqlite_path,
        bs_mod=bs_mod,
        baostock_list_day=bday,
    )
    if args.limit and args.limit > 0:
        codes = codes[: int(args.limit)]
    print(
        f"共 {len(codes)} 只，区间 {args.start_date} ~ {end}，provider={args.provider}，输出 {data_dir}"
    )

    ok_n = skip_n = fail_n = 0
    t0 = time.time()

    try:
        from tqdm import tqdm  # type: ignore[import-not-found]

        use_bar = True
    except ImportError:
        tqdm = None  # type: ignore[assignment]
        use_bar = False

    ak_mod: Any = None
    if args.provider == "akshare":
        import akshare as ak_mod  # type: ignore[import-not-found]

    iterator = tqdm(codes, desc="Downloading") if use_bar and tqdm else codes
    start_bs = _ymd_to_yyyy_mm_dd(args.start_date)
    end_bs = _ymd_to_yyyy_mm_dd(end)
    bs_flag = _ak_adjust_to_bs_flag(args.adjust)

    try:
        for i, code in enumerate(iterator):
            if args.provider == "baostock":
                stem = (
                    str(code).split(".", 1)[-1]
                    if "." in str(code)
                    else str(code).zfill(6)
                )
                out_path = data_dir / f"{stem}.csv"
            else:
                out_path = data_dir / f"{str(code).zfill(6)}.csv"
            if args.resume and out_path.is_file() and out_path.stat().st_size > 50:
                skip_n += 1
                continue
            try:
                if args.provider == "baostock":
                    assert bs_mod is not None
                    ok = _download_one_baostock(
                        bs_mod,
                        code,
                        start_yyyy_mm_dd=start_bs,
                        end_yyyy_mm_dd=end_bs,
                        adjustflag=bs_flag,
                        out_path=out_path,
                    )
                else:
                    assert ak_mod is not None
                    ok = _download_one_akshare(
                        ak_mod,
                        code,
                        start_date=args.start_date,
                        end_date=end,
                        adjust=args.adjust,
                        out_path=out_path,
                    )
                if ok:
                    ok_n += 1
                else:
                    fail_n += 1
            except Exception as e:
                print(f"[err] {code}: {e}", file=sys.stderr)
                fail_n += 1
            time.sleep(max(0.0, float(args.sleep)))
            if not use_bar and (i + 1) % 200 == 0:
                print(
                    f"…进度 {i + 1}/{len(codes)}  成功 {ok_n} 跳过 {skip_n} 失败 {fail_n}  "
                    f"用时 {time.time() - t0:.0f}s"
                )
    finally:
        if bs_mod is not None:
            try:
                bs_mod.logout()
            except Exception:
                pass

    print(
        f"\n完成：成功 {ok_n}，跳过 {skip_n}，失败 {fail_n}，目录 {data_dir} "
        f"（总耗时 {time.time() - t0:.1f}s）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
