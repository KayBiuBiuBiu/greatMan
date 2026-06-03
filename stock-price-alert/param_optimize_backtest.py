#!/usr/bin/env python3
"""参数优化工具 - 基于回放历史进场信号

通过重新计算历史数据中的进场信号，测试不同参数组合的表现
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
import itertools
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kline_store import open_store_connection
from quote_eastmoney import secid_for
from quant_core.selector import load_df


def secid_for_code(code: str) -> str:
    """Convert code to secid"""
    c = str(code).strip().zfill(6)
    market = "sh" if c.startswith(("6", "9")) else "sz"
    return secid_for(c, market)


def get_entry_signal_result(
    df: pd.DataFrame | None, rsi_threshold: float, volume_ratio: float, price_limit: float
) -> bool:
    """根据参数计算进场信号是否满足"""
    if df is None or len(df) < 20:
        return False

    close = df["close"]
    volume = df["volume"]

    # 1. 均线金叉
    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    golden_cross = (ma5.iloc[-2] <= ma10.iloc[-2]) and (ma5.iloc[-1] > ma10.iloc[-1])

    if not golden_cross:
        return False

    # 2. RSI 超卖
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_value = rsi.iloc[-1]

    if rsi_value >= rsi_threshold:
        return False

    # 3. 成交量
    volume_avg_5d = volume.tail(6)[:-1].mean()
    volume_today = volume.iloc[-1]
    volume_ratio_value = volume_today / volume_avg_5d if volume_avg_5d > 0 else 0

    if volume_ratio_value <= volume_ratio:
        return False

    # 4. 价格位置
    ma20 = close.rolling(20).mean().iloc[-1]
    price_today = close.iloc[-1]

    if price_today >= ma20 * price_limit:
        return False

    return True


def get_future_return(db_path: Path, code: str, pick_date: str, days: int = 10) -> float | None:
    """获取future return"""
    conn = open_store_connection(db_path)
    secid = secid_for_code(code)

    # 获取pick_date的价格
    query = "SELECT close FROM daily_klines WHERE secid = ? AND trade_date = ?"
    row = conn.execute(query, (secid, pick_date)).fetchone()

    if not row:
        return None

    pick_price = float(row["close"])

    # 获取之后的数据
    query2 = (
        "SELECT close FROM daily_klines WHERE secid = ? AND trade_date > ? "
        "ORDER BY trade_date ASC LIMIT ?"
    )
    future_rows = conn.execute(query2, (secid, pick_date, days + 5)).fetchall()

    if len(future_rows) == 0:
        return None

    if len(future_rows) >= days:
        future_price = float(future_rows[days - 1]["close"])
    else:
        future_price = float(future_rows[-1]["close"])

    return (future_price - pick_price) / pick_price * 100


def load_historical_picks(picks_dir: Path) -> dict[str, list[str]]:
    """加载历史picks的stocks代码"""
    picks_by_date = {}

    for picks_file in sorted(picks_dir.glob("*.json")):
        try:
            with open(picks_file) as f:
                data = json.load(f)
        except Exception:
            continue

        stem = picks_file.stem
        try:
            pick_date = datetime.strptime(stem, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            continue

        stocks = data.get("stocks", []) or data.get("items", []) or data.get("picks", [])
        codes = [stock.get("code", "").strip().zfill(6) for stock in stocks if stock.get("code")]

        picks_by_date[pick_date] = codes

    return picks_by_date


def main():
    parser = argparse.ArgumentParser(description="参数优化 - 基于回放历史信号")
    parser.add_argument("-c", "--config", type=Path, default=Path("config.json"))
    parser.add_argument("--history-dir", type=Path, default=Path("data/picks_history"))
    parser.add_argument("--quick-test", action="store_true", help="快速测试")

    args = parser.parse_args()

    # 加载配置
    with open(args.config) as f:
        cfg = json.load(f)

    db_path = Path(cfg.get("kline_store", {}).get("db_path", "data/daily_klines.db"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return

    print("📊 参数优化 - 基于回放历史信号")
    print("=" * 70)

    # 加载历史picks
    print("\n1️⃣ 加载历史picks...")
    picks_by_date = load_historical_picks(args.history_dir)
    print(f"✅ 加载了 {len(picks_by_date)} 个交易日的picks")

    # 定义参数搜索空间
    if args.quick_test:
        param_grid = {
            "rsi_threshold": [25, 30, 35],
            "volume_ratio": [1.3, 1.5],
            "price_limit": [1.05, 1.10],
        }
        print("\n🚀 快速测试模式")
    else:
        param_grid = {
            "rsi_threshold": [15, 20, 25, 30, 35, 40],
            "volume_ratio": [1.2, 1.4, 1.6, 1.8, 2.0],
            "price_limit": [1.0, 1.05, 1.10, 1.15],
        }
        print("\n🔍 完整参数搜索模式")

    # 网格搜索
    print("\n2️⃣ 运行网格搜索...")

    param_names = list(param_grid.keys())
    param_values = [param_grid[name] for name in param_names]

    results = []
    total_combos = 1
    for vals in param_values:
        total_combos *= len(vals)

    print(f"  测试 {total_combos} 个参数组合...")

    combo_idx = 0
    for param_combo in itertools.product(*param_values):
        combo_idx += 1
        param_dict = dict(zip(param_names, param_combo))

        # 用这个参数组合回放历史
        total_picks = 0
        successful_picks = 0

        for pick_date, codes in picks_by_date.items():
            for code in codes:
                total_picks += 1

                # 加载K线数据
                df = load_df(code, lookback=60)

                # 检查是否满足进场信号
                if not get_entry_signal_result(
                    df,
                    param_dict["rsi_threshold"],
                    param_dict["volume_ratio"],
                    param_dict["price_limit"],
                ):
                    continue

                # 计算未来回报
                future_return = get_future_return(db_path, code, pick_date, days=10)
                if future_return is not None and future_return >= 3.0:
                    successful_picks += 1

        winrate = successful_picks / total_picks if total_picks > 0 else 0

        results.append(
            {
                "params": param_dict,
                "total_picks": total_picks,
                "wins": successful_picks,
                "winrate": winrate,
            }
        )

        if combo_idx % max(1, total_combos // 10) == 0:
            print(f"    进度: {combo_idx}/{total_combos} ({combo_idx*100//total_combos}%)")

    # 排序结果
    sorted_results = sorted(results, key=lambda x: (x["winrate"], -x["total_picks"]), reverse=True)

    print("\n" + "=" * 70)
    print("📊 优化结果")
    print("=" * 70)

    print(f"\n🏆 Top 10 参数组合:\n")
    for i, result in enumerate(sorted_results[:10], 1):
        params = result["params"]
        print(
            f"{i}. 胜率 {result['winrate']:.1%} (N={result['total_picks']}, 赢 {result['wins']})"
        )
        print(
            f"   RSI < {params['rsi_threshold']}, "
            f"成交量 > {params['volume_ratio']}x, "
            f"价格 < {params['price_limit']}x"
        )

    # 保存结果
    output_file = Path("param_optimization_final.json")
    with open(output_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "total_combos_tested": len(results),
                "best_params": sorted_results[0]["params"],
                "best_winrate": sorted_results[0]["winrate"],
                "top_10": [
                    {
                        "params": r["params"],
                        "winrate": r["winrate"],
                        "total_picks": r["total_picks"],
                        "wins": r["wins"],
                    }
                    for r in sorted_results[:10]
                ],
            },
            f,
            indent=2,
        )

    print(f"\n✅ 结果已保存: {output_file}")


if __name__ == "__main__":
    main()
