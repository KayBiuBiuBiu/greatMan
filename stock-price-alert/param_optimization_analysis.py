#!/usr/bin/env python3
"""参数优化分析 - 简化版

这个脚本分析历史pick中股票的成功率，帮助识别最优的参数组合
基于已有的历史数据，快速进行参数评估
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
import itertools

import numpy as np

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kline_store import open_store_connection
from quote_eastmoney import secid_for


def secid_for_code(code: str) -> str:
    """Convert code to secid"""
    c = str(code).strip().zfill(6)
    market = "sh" if c.startswith(("6", "9")) else "sz"
    return secid_for(c, market)


def load_historical_picks(picks_dir: Path) -> dict[str, list[dict]]:
    """加载所有历史picks数据"""
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
        picks_by_date[pick_date] = stocks

    return picks_by_date


def get_returns_for_pick(
    db_path: Path, code: str, pick_date: str, days_ahead: int = 10
) -> float | None:
    """获取某只股票从pick_date开始的回报率"""
    conn = open_store_connection(db_path)
    secid = secid_for_code(code)

    # 获取pick_date当天的价格
    query = "SELECT close FROM daily_klines WHERE secid = ? AND trade_date = ?"
    pick_row = conn.execute(query, (secid, pick_date)).fetchone()

    if not pick_row:
        return None

    pick_price = float(pick_row["close"])

    # 获取pick_date之后的数据
    query2 = (
        "SELECT close FROM daily_klines WHERE secid = ? AND trade_date > ? "
        "ORDER BY trade_date ASC LIMIT ?"
    )
    future_rows = conn.execute(query2, (secid, pick_date, days_ahead + 5)).fetchall()

    if len(future_rows) == 0:
        return None

    # 取第days_ahead条，或最后一条
    if len(future_rows) >= days_ahead:
        future_price = float(future_rows[days_ahead - 1]["close"])
    else:
        future_price = float(future_rows[-1]["close"])

    return_pct = (future_price - pick_price) / pick_price * 100
    return return_pct


def analyze_stock_performance(
    db_path: Path, picks_by_date: dict[str, list[dict]], days_ahead: int = 10
) -> dict[str, Any]:
    """分析所有stock的表现"""
    performance = []

    total_stocks = sum(len(stocks) for stocks in picks_by_date.values())
    processed = 0

    for pick_date, stocks in picks_by_date.items():
        for stock in stocks:
            processed += 1
            if processed % 20 == 0:
                print(f"  处理进度: {processed}/{total_stocks}")

            code = stock.get("code", "").strip().zfill(6)
            if not code:
                continue

            return_pct = get_returns_for_pick(db_path, code, pick_date, days_ahead)
            if return_pct is None:
                continue

            success = return_pct >= 3.0

            performance.append(
                {
                    "code": code,
                    "name": stock.get("name", ""),
                    "pick_date": pick_date,
                    "return_pct": return_pct,
                    "success": success,
                    "score": stock.get("score", 0),
                }
            )

    return performance


def simulate_parameters(
    performance: list[dict], rsi_threshold: float, volume_ratio: float, price_limit: float
) -> dict[str, Any]:
    """模拟参数组合的效果

    注意：这里使用score作为RSI的代理
    """
    # 简化版过滤：用score模拟RSI (score越低越像超卖)
    filtered = []

    for item in performance:
        # 模拟RSI: score转换为0-100的类似指标
        simulated_rsi = max(0, min(100, 50 - item["score"] * 5))

        # 应用参数过滤
        if simulated_rsi >= rsi_threshold:
            continue

        filtered.append(item)

    if not filtered:
        return {"winrate": 0, "avg_return": 0, "count": 0}

    wins = sum(1 for p in filtered if p["success"])
    winrate = wins / len(filtered)
    avg_return = np.mean([p["return_pct"] for p in filtered])

    return {
        "winrate": winrate,
        "avg_return": avg_return,
        "count": len(filtered),
        "wins": wins,
    }


def main():
    parser = argparse.ArgumentParser(description="参数优化分析")
    parser.add_argument("-c", "--config", type=Path, default=Path("config.json"))
    parser.add_argument("--history-dir", type=Path, default=Path("data/picks_history"))
    parser.add_argument("--horizon", type=int, default=10, help="评估天数")
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

    print("📊 参数优化分析")
    print("=" * 70)

    # 加载历史picks
    print("\n1️⃣ 加载历史picks...")
    picks_by_date = load_historical_picks(args.history_dir)
    print(f"✅ 加载了 {len(picks_by_date)} 个交易日的picks")

    # 分析性能
    print("\n2️⃣ 分析stock性能...")
    performance = analyze_stock_performance(db_path, picks_by_date, args.horizon)
    print(f"✅ 分析了 {len(performance)} 个stock")

    # 统计总体数据
    wins = sum(1 for p in performance if p["success"])
    total_winrate = wins / len(performance) if performance else 0
    avg_return = np.mean([p["return_pct"] for p in performance]) if performance else 0

    print(f"\n📈 总体统计:")
    print(f"  总股票数: {len(performance)}")
    print(f"  总胜率: {total_winrate:.1%}")
    print(f"  平均收益: {avg_return:+.2f}%")

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
    print("\n3️⃣ 运行网格搜索...")

    param_names = list(param_grid.keys())
    param_values = [param_grid[name] for name in param_names]

    results = []
    total_combos = 1
    for vals in param_values:
        total_combos *= len(vals)

    print(f"  测试 {total_combos} 个参数组合...")

    for combo_idx, param_combo in enumerate(itertools.product(*param_values), 1):
        param_dict = dict(zip(param_names, param_combo))
        result = simulate_parameters(
            performance,
            param_dict["rsi_threshold"],
            param_dict["volume_ratio"],
            param_dict["price_limit"],
        )
        result["params"] = param_dict

        results.append(result)

        if combo_idx % max(1, total_combos // 10) == 0:
            print(f"    进度: {combo_idx}/{total_combos}")

    # 排序结果
    sorted_results = sorted(results, key=lambda x: (x["winrate"], x["avg_return"]), reverse=True)

    print("\n" + "=" * 70)
    print("📊 优化结果")
    print("=" * 70)

    print(f"\n🏆 Top 10 参数组合:\n")
    for i, result in enumerate(sorted_results[:10], 1):
        params = result["params"]
        print(
            f"{i}. 胜率 {result['winrate']:.1%} "
            f"(平均 {result['avg_return']:+.2f}%, N={result['count']})"
        )
        print(
            f"   RSI < {params['rsi_threshold']}, "
            f"成交量 > {params['volume_ratio']}x, "
            f"价格 < {params['price_limit']}x"
        )

    # 与当前参数对比
    print(f"\n📌 当前参数 (SHORT_TERM_TRADING_CONFIG):")
    current_params = {"rsi_threshold": 35, "volume_ratio": 1.5, "price_limit": 1.1}
    print(f"  RSI < 35, 成交量 > 1.5x, 价格 < 1.1x")

    # 找当前参数在排序结果中的位置
    for idx, result in enumerate(sorted_results):
        if (
            result["params"]["rsi_threshold"] == 35
            and result["params"]["volume_ratio"] == 1.5
            and result["params"]["price_limit"] == 1.1
        ):
            improvement = (
                (sorted_results[0]["winrate"] - result["winrate"]) * 100
                if sorted_results[0]["winrate"] > 0
                else 0
            )
            print(f"  当前参数排名: 第 {idx+1} / {len(sorted_results)}")
            print(f"  胜率: {result['winrate']:.1%}, 平均收益: {result['avg_return']:+.2f}%")
            if improvement > 0:
                print(f"  💡 最优参数可提升 {improvement:.1f} 个百分点")
            break

    # 保存结果
    output_file = Path("param_optimization_analysis.json")
    with open(output_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "horizon_days": args.horizon,
                "total_stocks_analyzed": len(performance),
                "overall_winrate": total_winrate,
                "overall_avg_return": avg_return,
                "best_params": sorted_results[0]["params"],
                "best_winrate": sorted_results[0]["winrate"],
                "best_avg_return": sorted_results[0]["avg_return"],
                "top_10": [
                    {
                        "params": r["params"],
                        "winrate": r["winrate"],
                        "avg_return": r["avg_return"],
                        "count": r["count"],
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
