from __future__ import annotations

import akshare as ak
import baostock as bs
import json
import random
import pandas as pd
import time
from datetime import datetime
from pathlib import Path

_BS_LOGIN_OK = False


def _score_sort_key(row: dict) -> tuple[float, float]:
    """按分数降序；同分用随机次序打破平局，避免 JSON/展示里按代码挤成一片 000/002。"""
    try:
        s = float(row.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        s = 0.0
    return (-s, random.random())


def _ensure_bs_login() -> bool:
    global _BS_LOGIN_OK
    if _BS_LOGIN_OK:
        return True
    try:
        lg = bs.login()
        _BS_LOGIN_OK = getattr(lg, "error_code", "") == "0"
    except Exception:
        _BS_LOGIN_OK = False
    return _BS_LOGIN_OK


def _safe_bs_logout() -> None:
    global _BS_LOGIN_OK
    if not _BS_LOGIN_OK:
        return
    try:
        bs.logout()
    except Exception:
        pass
    _BS_LOGIN_OK = False


def _normalize_kline_df(df):
    if df is None or df.empty:
        return None
    out = df.copy().rename(
        columns={
            "日期": "date",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
        }
    )
    for col in ("close", "high", "low", "volume"):
        if col not in out.columns:
            return None
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["close", "high", "low", "volume"])
    return out


def load_df(code: str, *, lookback: int = 60):
    try:
        if _ensure_bs_login():
            code_prefix = "sh." + code if code.startswith("6") else "sz." + code
            rs = bs.query_history_k_data_plus(
                code=code_prefix,
                start_date="2018-01-01",
                fields="date,close,high,low,volume",
                frequency="d",
                adjustflag="3",
            )
            rows = []
            while (rs.error_code == "0") and rs.next():
                rows.append(rs.get_row_data())
            df = pd.DataFrame(rows, columns=rs.fields if rows else [])
            df = _normalize_kline_df(df)
            if df is not None:
                df = df.tail(max(lookback, 60)).copy()
                if len(df) >= 30:
                    return df
    except Exception:
        pass

    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq").tail(max(lookback, 60))
        df = _normalize_kline_df(df)
        if df is not None and len(df) >= 30:
            return df
    except Exception:
        pass
    return None


def get_real_score(code: str, df: pd.DataFrame | None = None) -> float:
    k = df if df is not None else load_df(code, lookback=120)
    if k is None or len(k) < 30:
        return 3.0
    try:
        close = float(k["close"].iloc[-1])
        ma20 = float(k["close"].rolling(20).mean().iloc[-1])
        ma60 = float(k["close"].rolling(60).mean().iloc[-1])
        trend = 8 if (close > ma20 > ma60) else (5 if close > ma20 else 2)

        high = float(k["high"].max())
        low = float(k["low"].min())
        box_pos = (close - low) / (high - low) if high != low else 0.5
        box = 7 if 0.2 < box_pos < 0.6 else 4

        volatility = float(k["close"].pct_change().std())
        vol = 6 if 0.02 < volatility < 0.08 else 3

        vol5 = float(k["volume"].rolling(5).mean().iloc[-1])
        vol20 = float(k["volume"].rolling(20).mean().iloc[-1])
        volume = 7 if vol5 > vol20 * 1.2 else 4

        total = (trend * 3 + box * 2 + vol * 2 + volume * 2) / 9
        return round(min(total, 10.0), 1)
    except Exception:
        return 3.0


def _run_backtest_on_df(df: pd.DataFrame, years: int) -> dict:
    use_n = max(120, 252 * int(years) + 70)
    x = df.tail(use_n).copy()
    if len(x) < 80:
        return {"profit": 0.0, "win": 0.0, "trades": 0, "note": "样本不足"}
    x["ma20"] = x["close"].rolling(20).mean()
    x["ma60"] = x["close"].rolling(60).mean()
    x = x.dropna().reset_index(drop=True)
    if len(x) < 40:
        return {"profit": 0.0, "win": 0.0, "trades": 0, "note": "样本不足"}

    trades: list[float] = []
    for i in range(1, len(x)):
        ma20_prev = float(x["ma20"].iloc[i - 1])
        ma60_prev = float(x["ma60"].iloc[i - 1])
        ma20_now = float(x["ma20"].iloc[i])
        ma60_now = float(x["ma60"].iloc[i])
        if not (ma20_prev < ma60_prev and ma20_now > ma60_now):
            continue
        buy = float(x["close"].iloc[i])
        if buy <= 0:
            continue
        decided = False
        for j in range(i + 1, min(i + 20, len(x))):
            pct = (float(x["close"].iloc[j]) / buy - 1.0) * 100.0
            if pct >= 8.0:
                trades.append(8.0)
                decided = True
                break
            if pct <= -4.0:
                trades.append(-4.0)
                decided = True
                break
        if not decided:
            last_j = min(i + 20, len(x) - 1)
            pct = (float(x["close"].iloc[last_j]) / buy - 1.0) * 100.0
            trades.append(round(pct, 2))

    if not trades:
        return {"profit": 0.0, "win": 0.0, "trades": 0, "note": "无交易信号"}
    profit = round(sum(trades), 2)
    win = round(100.0 * len([t for t in trades if t > 0]) / len(trades), 1)
    return {"profit": profit, "win": win, "trades": len(trades), "note": "OK"}


def _classify(
    score: float,
    bt1: dict,
    bt3: dict,
    bt5: dict,
    *,
    th: dict[str, float],
) -> tuple[str, str]:
    p1 = float(bt1.get("profit", 0.0))
    w1 = float(bt1.get("win", 0.0))
    p3 = float(bt3.get("profit", 0.0))
    p5 = float(bt5.get("profit", 0.0))
    sq = float(th.get("score_min_quality", 7.0))
    sw = float(th.get("score_min_watch", 5.5))
    p1_min = float(th.get("profit_1y_min", 0.0))
    w1_min = float(th.get("win_1y_min", 50.0))
    p3_floor = float(th.get("profit_3y_floor", -8.0))
    if score >= sq and p1 >= p1_min and w1 >= w1_min and p3 >= p3_floor:
        return "优质股", "因子与回测双重达标"
    if score >= sw and p1 >= -3 and w1 >= 40 and p3 >= -15:
        return "观察股", "基本达标，建议继续跟踪"
    if score < 4.5:
        return "淘汰股", "当前因子偏弱"
    if w1 < 35:
        return "淘汰股", "短期胜率过低"
    if p3 < -20 or p5 < -30:
        return "淘汰股", "中长期回测回撤过大"
    return "淘汰股", "历史回测不达标"


def _split_codes_by_board(codes: list[str]) -> tuple[list[str], list[str], list[str]]:
    """按板块拆分代码。全市场 sorted 后取前 N 只会全是 000/002 等 0 字头，300/301 与 6 字头永远进不了样本。"""
    cy: list[str] = []
    sh: list[str] = []
    sz: list[str] = []
    for raw in codes:
        c = str(raw).strip()
        if len(c) != 6 or not c.isdigit():
            continue
        if c.startswith(("300", "301")):
            cy.append(c)
        elif c.startswith("6"):
            sh.append(c)
        else:
            sz.append(c)
    cy.sort()
    sh.sort()
    sz.sort()
    return cy, sh, sz


def _allocate_proportional(sizes: list[int], max_n: int) -> list[int]:
    """把 max_n 按 sizes 比例拆成整数份（最大余额法），与 sizes 等长。"""
    total = sum(sizes)
    if total <= 0 or max_n <= 0:
        return [0] * len(sizes)
    n = min(max_n, total)
    exact = [n * s / total for s in sizes]
    floors = [int(x) for x in exact]
    rem = n - sum(floors)
    order = sorted(
        range(len(sizes)),
        key=lambda i: exact[i] - floors[i],
        reverse=True,
    )
    for k in range(rem):
        floors[order[k]] += 1
    return floors


def _proportional_random_sample(
    sz_c: list[str],
    sh_c: list[str],
    cy_c: list[str],
    max_n: int,
    *,
    rng: random.Random,
) -> list[str]:
    """
    三板块按全市场只数比例分配扫描名额，板内随机抽样；打分后全局排序，不强制每板都进优质名单。
    """
    pools = (sz_c, sh_c, cy_c)
    sizes = [len(p) for p in pools]
    total = sum(sizes)
    if total == 0:
        return []
    n = min(max_n, total)
    alloc = _allocate_proportional(sizes, n)
    alloc = [min(alloc[i], sizes[i]) for i in range(3)]
    short = n - sum(alloc)
    spare = [sizes[i] - alloc[i] for i in range(3)]
    si = 0
    while short > 0 and sum(spare) > 0:
        i = si % 3
        si += 1
        if spare[i] <= 0:
            continue
        alloc[i] += 1
        spare[i] -= 1
        short -= 1

    out: list[str] = []
    for pool, k in zip(pools, alloc):
        if k <= 0:
            continue
        if k >= len(pool):
            out.extend(pool)
        else:
            out.extend(rng.sample(pool, k))
    return out


def run_daily_selector(cfg, limit=250, top_n_per_strategy=30):
    print("⏳ 获取全市场A股列表...")
    df_sh = ak.stock_info_sh_name_code("主板A股")
    try:
        df_sz = ak.stock_info_sz_name_code("A股")
    except Exception:
        df_sz = ak.stock_info_sz_name_code("A股列表")

    stock_list = [str(r["证券代码"]).strip() for _, r in df_sh.iterrows()]
    for _, r in df_sz.iterrows():
        c = str(r.get("证券代码") or r.get("A股代码") or "").strip()
        if c:
            stock_list.append(c)
    stock_list = sorted(set(stock_list))
    print(f"✅ 全市场股票：{len(stock_list)} 只")

    max_scan = max(60, min(int(limit or 250), 4000))
    cy_c, sh_c, sz_c = _split_codes_by_board(stock_list)
    seed_s = str(cfg.get("daily_select_sample_seed") or "").strip()
    if seed_s:
        rng = random.Random(seed_s)
    else:
        rng = random.Random(datetime.now().strftime("%Y%m%d"))
    # 三板块按比例抽样 + 统一打分排序；优质/观察名单纯看分数与回测，不保证每板都有
    test_list = _proportional_random_sample(sz_c, sh_c, cy_c, max_scan, rng=rng)
    n_cy = sum(1 for x in test_list if x.startswith(("300", "301")))
    n_sh = sum(1 for x in test_list if x.startswith("6"))
    print(
        f"🔎 批量联动评分+回测：{len(test_list)} 只"
        f"（样本 深0字头 {len(test_list) - n_cy - n_sh} / 沪6字头 {n_sh} / 创业板 {n_cy}；"
        f"全市场创业板约 {len(cy_c)} 只）"
    )

    name_map = {}
    try:
        df_name = ak.stock_info_a_code_name()
        name_map = {str(x["code"]).strip(): str(x["name"]).strip() for _, x in df_name.iterrows()}
    except Exception:
        pass

    quality: list[dict] = []
    watch: list[dict] = []
    reject: list[dict] = []

    qs = cfg.get("quant_selector") if isinstance(cfg, dict) else {}
    th = qs if isinstance(qs, dict) else {}
    n_total = len(test_list)
    prog_every = max(50, min(200, n_total // 20 or 50))
    t0 = time.monotonic()
    try:
        for i, code in enumerate(test_list):
            df = load_df(code, lookback=252 * 5 + 80)
            score = get_real_score(code, df=df)
            name = name_map.get(code, f"股票{code}")
            bt1 = _run_backtest_on_df(df, 1) if df is not None else {"profit": 0, "win": 0, "trades": 0, "note": "无数据"}
            bt3 = _run_backtest_on_df(df, 3) if df is not None else {"profit": 0, "win": 0, "trades": 0, "note": "无数据"}
            bt5 = _run_backtest_on_df(df, 5) if df is not None else {"profit": 0, "win": 0, "trades": 0, "note": "无数据"}
            bucket, reason = _classify(score, bt1, bt3, bt5, th=th)
            row = {
                "code": code,
                "name": name,
                "score": score,
                "backtest": {"1y": bt1, "3y": bt3, "5y": bt5},
                "reason": reason,
            }
            if bucket == "优质股":
                quality.append(row)
            elif bucket == "观察股":
                watch.append(row)
            else:
                # 淘汰集合只保留简要字段，降低文件体积
                reject.append(
                    {
                        "code": code,
                        "name": name,
                        "score": score,
                        "reason": reason,
                    }
                )
            time.sleep(0.08)
            done = i + 1
            if done == 1 or done % prog_every == 0 or done == n_total:
                elapsed = time.monotonic() - t0
                rate = done / elapsed if elapsed > 0 else 0.0
                eta = (n_total - done) / rate if rate > 0 else 0.0
                print(
                    f"   … 选股进度 {done}/{n_total}（约 {rate:.1f} 只/秒，"
                    f"剩余约 {eta / 60:.1f} 分钟）",
                    flush=True,
                )
    finally:
        _safe_bs_logout()

    quality = sorted(quality, key=_score_sort_key)[:top_n_per_strategy]
    watch = sorted(watch, key=_score_sort_key)[: max(top_n_per_strategy, 20)]
    reject = sorted(reject, key=_score_sort_key)

    out_th = {
        "score_min": float(th.get("score_min_quality", 7.0)),
        "score_min_watch": float(th.get("score_min_watch", 5.5)),
        "profit_1y_min": float(th.get("profit_1y_min", 0.0)),
        "win_1y_min": float(th.get("win_1y_min", 50.0)),
        "profit_3y_floor": float(th.get("profit_3y_floor", -8.0)),
    }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scan_total": len(stock_list),
        "scan_used": len(test_list),
        "thresholds": out_th,
        "优质股": quality,
        "观察股": watch,
        "淘汰股": reject,
        "优质标的": quality,  # 兼容老键名
        "观察标的": watch,
        "淘汰标的": reject,
        "stocks": quality,  # 兼容旧读取
        "msg": "✅ 全自动联动完成：因子评分+历史回测双过滤",
    }


def save_daily_selector_result(result, output_path: Path):
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

