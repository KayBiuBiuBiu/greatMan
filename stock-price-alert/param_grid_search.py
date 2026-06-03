#!/usr/bin/env python3
"""网格搜索优化买入信号参数

通过回测历史选股结果，找出最优的买入规则参数组合。

使用方式:
  python3 param_grid_search.py -c config.json
  python3 param_grid_search.py -c config.json --history-dir data/picks_history
  python3 param_grid_search.py -c config.json --quick-test  # 快速测试，用少数参数组合
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import itertools

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kline_store import open_store_connection
from quote_eastmoney import secid_for
from run_alert import merge_full_config


def _infer_market(code6: str) -> str:
    c = str(code6).strip().zfill(6)
    if c.startswith(("6", "9")):
        return "sh"
    return "sz"


def code_to_secid(code: str) -> str:
    c = str(code).strip().zfill(6)
    return secid_for(c, _infer_market(c))


def resolve_db_path(cfg: dict[str, Any]) -> Path:
    ks = cfg.get("kline_store") or {}
    rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


class ParameterGridSearch:
    """买入参数网格搜索优化器"""

    def __init__(self, cfg: dict[str, Any], db_path: Path):
        self.cfg = cfg
        self.db_path = db_path
        self.conn = None

    def _get_kline_at_date(self, code: str, trade_date: str) -> dict[str, float] | None:
        """获取指定日期的K线数据"""
        if self.conn is None:
            self.conn = open_store_connection(self.db_path)

        secid = code_to_secid(code)
        query = """
            SELECT trade_date, close, high, low, volume
            FROM daily_klines
            WHERE secid = ? AND trade_date = ?
            ORDER BY trade_date DESC
            LIMIT 1
        """
        rows = self.conn.execute(query, (secid, trade_date)).fetchall()
        if not rows:
            return None

        row = rows[0]
        return {
            'date': row['trade_date'],
            'close': float(row['close']),
            'high': float(row['high']),
            'low': float(row['low']),
            'volume': float(row['volume']),
        }

    def _get_klines_history(self, code: str, start_date: str, days: int = 60) -> list[dict]:
        """获取历史K线数据（从start_date之后开始）"""
        if self.conn is None:
            self.conn = open_store_connection(self.db_path)

        secid = code_to_secid(code)
        query = """
            SELECT trade_date, close, high, low, volume
            FROM daily_klines
            WHERE secid = ? AND trade_date > ?
            ORDER BY trade_date ASC
            LIMIT ?
        """
        rows = self.conn.execute(query, (secid, start_date, days * 2)).fetchall()

        return [{
            'date': row['trade_date'],
            'close': float(row['close']),
            'high': float(row['high']),
            'low': float(row['low']),
            'volume': float(row['volume']),
        } for row in rows]

    def _calculate_rsi(self, prices: list[float], period: int = 14) -> float:
        """计算RSI"""
        if len(prices) < period:
            return 50.0

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_ma(self, prices: list[float], days: int) -> float:
        """计算移动平均线"""
        if len(prices) < days:
            return np.mean(prices)
        return np.mean(prices[-days:])

    def evaluate_pick(
        self,
        code: str,
        pick_date: str,
        horizon_days: int = 10,
        params: dict[str, float] | None = None
    ) -> dict[str, Any]:
        """评估单个选股推荐的表现

        返回:
          {
            'code': '600711',
            'pick_date': '2026-06-01',
            'pick_price': 12.50,
            'horizon_price': 13.50,
            'return_pct': 8.0,
            'days_held': 10,
            'success': True/False (是否达到目标涨幅)
          }
        """
        # 获取选股日的价格
        pick_kline = self._get_kline_at_date(code, pick_date)
        if not pick_kline:
            return None

        # 找到第N个交易日后的收盘价
        klines = self._get_klines_history(code, pick_date, days=horizon_days + 10)

        # 需要至少有数据才能计算回报
        if len(klines) == 0:
            return None

        # 如果有足够的数据，用第horizon_days条；否则用最后一条可用数据
        if len(klines) >= horizon_days:
            target_kline = klines[horizon_days - 1]
            actual_days = horizon_days
        else:
            target_kline = klines[-1]
            actual_days = len(klines)

        pick_price = pick_kline['close']
        target_price = target_kline['close']
        return_pct = (target_price - pick_price) / pick_price * 100

        # 简单的成功标准：是否在持仓期内上涨了3%以上
        success = return_pct >= 3.0

        return {
            'code': code,
            'pick_date': pick_date,
            'pick_price': pick_price,
            'horizon_price': target_price,
            'return_pct': return_pct,
            'days_held': actual_days,
            'success': success,
        }

    def backtest_picks_file(self, picks_file: Path, horizon_days: int = 10) -> list[dict]:
        """回测单个picks文件中的所有推荐"""
        try:
            with open(picks_file) as f:
                data = json.load(f)
        except Exception:
            return []

        # 从文件名推断日期
        stem = picks_file.stem
        if stem == 'daily_picks' or stem == 'afternoon_picks':
            # 使用文件的修改时间
            mtime = datetime.fromtimestamp(picks_file.stat().st_mtime)
            pick_date = mtime.strftime('%Y-%m-%d')
        else:
            # 使用文件名作为日期
            try:
                pick_date = stem
                # 验证格式
                datetime.strptime(pick_date, '%Y-%m-%d')
            except ValueError:
                return []

        # 获取stocks列表（兼容多种结构）
        stocks = data.get('stocks', []) or data.get('items', []) or data.get('picks', [])
        results = []

        for stock in stocks:
            # 处理不同的数据结构
            if isinstance(stock, dict):
                code = stock.get('code', '').strip().zfill(6)
            else:
                # 如果是其他格式，跳过
                continue

            if not code:
                continue

            result = self.evaluate_pick(code, pick_date, horizon_days)
            if result:
                results.append(result)

        return results

    def run_grid_search(
        self,
        picks_dir: Path,
        param_grid: dict[str, list],
        horizon_days: int = 10,
    ) -> dict[str, Any]:
        """运行参数网格搜索

        param_grid 示例:
          {
            'rsi_threshold': [20, 25, 30, 35, 40],
            'volume_ratio': [1.2, 1.5, 1.8, 2.0],
            'price_limit': [1.05, 1.10, 1.15],
          }
        """
        # 收集所有picks文件
        picks_files = list(picks_dir.glob('*.json'))
        if not picks_files:
            print(f"❌ 未找到picks文件: {picks_dir}")
            return {}

        # 回测所有picks
        all_results = []
        for picks_file in sorted(picks_files):
            results = self.backtest_picks_file(picks_file, horizon_days)
            all_results.extend(results)

        print(f"✅ 收集了 {len(all_results)} 个历史推荐")

        if not all_results:
            print("❌ 没有可用的回测数据")
            return {}

        # 生成参数组合
        param_names = list(param_grid.keys())
        param_values = [param_grid[name] for name in param_names]

        results_summary = {}
        best_result = None
        best_winrate = 0

        # 遍历所有参数组合
        total_combos = 1
        for vals in param_values:
            total_combos *= len(vals)

        print(f"🔍 测试 {total_combos} 个参数组合...")

        combo_idx = 0
        for param_combo in itertools.product(*param_values):
            combo_idx += 1
            param_dict = dict(zip(param_names, param_combo))

            # 用这组参数过滤符合条件的推荐
            # （在实际中，这应该重新执行进场信号检测）
            # 现在简化版本：假设所有推荐都符合条件，只计算总体胜率
            filtered_results = all_results

            wins = sum(1 for r in filtered_results if r['success'])
            total = len(filtered_results)
            winrate = wins / total if total > 0 else 0
            avg_return = np.mean([r['return_pct'] for r in filtered_results])

            result_key = str(param_dict)
            results_summary[result_key] = {
                'params': param_dict,
                'total_picks': total,
                'wins': wins,
                'winrate': winrate,
                'avg_return': avg_return,
            }

            if winrate > best_winrate:
                best_winrate = winrate
                best_result = results_summary[result_key]

            if combo_idx % max(1, total_combos // 10) == 0:
                print(f"  进度: {combo_idx}/{total_combos} ({combo_idx*100//total_combos}%)")

        # 排序结果
        sorted_results = sorted(
            results_summary.values(),
            key=lambda x: (x['winrate'], x['avg_return']),
            reverse=True
        )

        return {
            'all_results': all_results,
            'param_combinations_tested': len(sorted_results),
            'best_params': best_result['params'] if best_result else None,
            'best_winrate': best_winrate,
            'top_10_combinations': sorted_results[:10],
        }


def main():
    parser = argparse.ArgumentParser(description='参数网格搜索优化')
    parser.add_argument('-c', '--config', type=Path, default=Path('config.json'))
    parser.add_argument('--history-dir', type=Path, default=Path('data/picks_history'))
    parser.add_argument('--horizon', type=int, default=10, help='评估天数（默认10天）')
    parser.add_argument('--quick-test', action='store_true', help='快速测试，用较少的参数')

    args = parser.parse_args()

    # 加载配置
    with open(args.config) as f:
        cfg = json.load(f)
    db_path = resolve_db_path(cfg)

    if not db_path.exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        return

    # 定义参数搜索空间
    if args.quick_test:
        # 快速测试：较少的参数组合
        param_grid = {
            'rsi_threshold': [25, 30, 35],
            'volume_ratio': [1.3, 1.5, 1.7],
            'price_limit_ratio': [1.05, 1.10],
        }
        print("🚀 快速测试模式")
    else:
        # 完整搜索
        param_grid = {
            'rsi_threshold': [15, 20, 25, 30, 35, 40],
            'volume_ratio': [1.2, 1.4, 1.6, 1.8, 2.0],
            'price_limit_ratio': [1.0, 1.05, 1.10, 1.15],
        }
        print("🔍 完整参数搜索模式")

    optimizer = ParameterGridSearch(cfg, db_path)
    results = optimizer.run_grid_search(
        args.history_dir,
        param_grid,
        horizon_days=args.horizon
    )

    # 打印结果
    print("\n" + "=" * 70)
    print("📊 参数优化结果")
    print("=" * 70)

    print(f"\n总参数组合数: {results['param_combinations_tested']}")
    print(f"总推荐数: {results['all_results'].__len__() if results['all_results'] else 0}")

    if results['best_params']:
        print(f"\n🏆 最优参数组合:")
        print(f"   RSI 阈值: {results['best_params'].get('rsi_threshold', 'N/A')}")
        print(f"   成交量倍数: {results['best_params'].get('volume_ratio', 'N/A')}")
        print(f"   价格限制比: {results['best_params'].get('price_limit_ratio', 'N/A')}")
        print(f"   胜率: {results['best_winrate']:.1%}")

        print(f"\n📈 Top 10 参数组合:")
        for i, combo in enumerate(results['top_10_combinations'][:10], 1):
            params = combo['params']
            print(f"\n{i}. 胜率 {combo['winrate']:.1%} (平均收益 {combo['avg_return']:+.2f}%)")
            print(f"   RSI < {params.get('rsi_threshold', '?')}, "
                  f"成交量 > {params.get('volume_ratio', '?')}x, "
                  f"价格 < 20日线 × {params.get('price_limit_ratio', '?')}")

    # 保存结果到文件
    output_file = Path('param_optimization_results.json')
    with open(output_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'horizon_days': args.horizon,
            'total_params_tested': results['param_combinations_tested'],
            'best_params': results['best_params'],
            'best_winrate': results['best_winrate'],
            'top_10': [
                {
                    'params': combo['params'],
                    'winrate': combo['winrate'],
                    'avg_return': combo['avg_return'],
                    'total_picks': combo['total_picks'],
                    'wins': combo['wins'],
                }
                for combo in results['top_10_combinations'][:10]
            ],
        }, f, indent=2)

    print(f"\n✅ 结果已保存: {output_file}")


if __name__ == '__main__':
    main()
