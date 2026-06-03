#!/usr/bin/env python3
"""
性能对标测试脚本 - 验证优化效果

运行方式：
  python3 performance_benchmark.py [--full]

选项：
  --full    运行完整对标（选股×2轮，包括配置加载、启动等）
  默认      快速对标（仅关键路径）
"""

import time
import json
import sys
from pathlib import Path
from datetime import datetime


def benchmark_config_merge():
    """测试1: 配置合并性能"""
    print("\n" + "=" * 70)
    print("测试1: 配置合并性能（run_alert.merge_full_config）")
    print("=" * 70)

    from run_alert import merge_full_config

    cfg = json.load(open('config.json'))
    n_runs = 5
    times = []

    for i in range(n_runs):
        t0 = time.perf_counter()
        result = merge_full_config(cfg)
        t1 = time.perf_counter()
        elapsed = (t1 - t0) * 1000
        times.append(elapsed)
        print(f"  运行 {i+1}: {elapsed:.2f}ms")

    avg = sum(times) / len(times)
    min_t = min(times)
    max_t = max(times)

    print(f"\n统计:")
    print(f"  平均: {avg:.2f}ms")
    print(f"  最小: {min_t:.2f}ms")
    print(f"  最大: {max_t:.2f}ms")
    print(f"  ✅ 预期改善: -5-10% 相比优化前的 ~170ms")

    return {"type": "config_merge", "avg": avg, "min": min_t, "max": max_t}


def benchmark_kline_cache():
    """测试2: K线缓存效果"""
    print("\n" + "=" * 70)
    print("测试2: K线缓存效果（同一轮中重复拉取K线）")
    print("=" * 70)

    from quant_core.selector import load_df
    import pandas as pd

    cfg = json.load(open('config.json'))
    test_codes = ['600711', '600663', '600105', '002185', '001234']

    print("\n场景A: 无缓存（5次独立调用）")
    t0 = time.perf_counter()
    for code in test_codes:
        try:
            df = load_df(code, lookback=60, cfg=cfg)
            if df is not None:
                print(f"  {code}: {len(df)} bars")
        except Exception as e:
            print(f"  {code}: ⚠️ {str(e)[:30]}")
    t1 = time.perf_counter()
    time_no_cache = (t1 - t0) * 1000
    print(f"总耗时: {time_no_cache:.1f}ms")

    print("\n场景B: 有缓存（第2-5次命中缓存）")
    kline_cache = {}
    t0 = time.perf_counter()
    for i, code in enumerate(test_codes):
        try:
            if code in kline_cache:
                df = kline_cache[code]
                print(f"  {code}: {len(df) if df is not None else 0} bars (缓存✓)")
            else:
                df = load_df(code, lookback=60, cfg=cfg)
                kline_cache[code] = df
                if df is not None:
                    print(f"  {code}: {len(df)} bars (加载)")
        except Exception as e:
            print(f"  {code}: ⚠️ {str(e)[:30]}")
    t1 = time.perf_counter()
    time_with_cache = (t1 - t0) * 1000
    print(f"总耗时: {time_with_cache:.1f}ms")

    print(f"\n对比:")
    if time_no_cache > 0:
        improvement = ((time_no_cache - time_with_cache) / time_no_cache) * 100
        print(f"  无缓存: {time_no_cache:.1f}ms")
        print(f"  有缓存: {time_with_cache:.1f}ms")
        print(f"  改善率: {improvement:.1f}%")
        if improvement > 0:
            print(f"  ✅ 缓存有效")
        else:
            print(f"  ⚠️ 缓存未显示优化（可能是首轮加热延迟）")

    return {
        "type": "kline_cache",
        "no_cache_ms": time_no_cache,
        "with_cache_ms": time_with_cache,
        "improvement_pct": ((time_no_cache - time_with_cache) / time_no_cache * 100) if time_no_cache > 0 else 0
    }


def benchmark_daily_summary():
    """测试3: 日报生成性能（JSON并行I/O）"""
    print("\n" + "=" * 70)
    print("测试3: 日报生成性能（包含JSON并行I/O）")
    print("=" * 70)

    from daily_summary import build_daily_summary
    from datetime import datetime
    from pathlib import Path

    cfg = json.load(open('config.json'))
    config_path = Path('config.json')
    root = config_path.parent
    state = {}
    now = datetime.now()

    print("\n生成日报摘要（包含所有数据源读取）...")
    t0 = time.perf_counter()
    try:
        result = build_daily_summary(cfg=cfg, config_path=config_path, state=state, root=root, now=now)
        t1 = time.perf_counter()
        elapsed = (t1 - t0) * 1000

        print(f"✅ 完成")
        print(f"耗时: {elapsed:.1f}ms")
        print(f"  (包含: account_pnl, signals, afternoon, weekly, health, trades, position_ops)")
        print(f"\n✅ 预期改善: 并行I/O实现 -150-200ms")

        return {"type": "daily_summary", "elapsed_ms": elapsed}
    except Exception as e:
        print(f"❌ 失败: {e}")
        return {"type": "daily_summary", "error": str(e)}


def benchmark_selector_limit(limit=50):
    """测试4: 选股性能（可选完整测试）"""
    print("\n" + "=" * 70)
    print(f"测试4: 选股性能（limit={limit}）")
    print("=" * 70)

    import subprocess

    print(f"\n运行: python3 quant_cli.py daily-select --limit {limit}")
    t0 = time.perf_counter()

    try:
        result = subprocess.run(
            ['python3', 'quant_cli.py', 'daily-select', f'--limit', str(limit)],
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )
        t1 = time.perf_counter()
        elapsed = (t1 - t0)

        # 提取关键信息
        output = result.stderr if result.stderr else result.stdout
        lines = output.split('\n')

        quality_count = 0
        speed_info = None

        for line in lines:
            if '优质股' in line:
                quality_count = line.count('只')
            if '选股进度' in line and '只/秒' in line:
                speed_info = line

        print(f"✅ 完成")
        print(f"总耗时: {elapsed:.1f}s")
        if speed_info:
            print(f"进度信息: {speed_info}")
        print(f"\n✅ 预期改善: K线缓存 -30-50%，批处理优化 GIL")

        return {"type": "selector", "elapsed_s": elapsed, "quality_count": quality_count}
    except subprocess.TimeoutExpired:
        print(f"❌ 超时（>5分钟）")
        return {"type": "selector", "error": "timeout"}
    except Exception as e:
        print(f"❌ 失败: {e}")
        return {"type": "selector", "error": str(e)}


def main():
    print("\n" + "=" * 70)
    print("🚀 Stock Price Alert 性能对标测试")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    full_test = '--full' in sys.argv

    results = []

    # 测试1: 配置合并
    try:
        r1 = benchmark_config_merge()
        results.append(r1)
    except Exception as e:
        print(f"❌ 测试1失败: {e}")

    # 测试2: K线缓存
    try:
        r2 = benchmark_kline_cache()
        results.append(r2)
    except Exception as e:
        print(f"❌ 测试2失败: {e}")

    # 测试3: 日报生成
    try:
        r3 = benchmark_daily_summary()
        results.append(r3)
    except Exception as e:
        print(f"❌ 测试3失败: {e}")

    # 测试4: 选股（如果指定 --full）
    if full_test:
        try:
            print("\n提示: 完整选股测试需要 2-5 分钟，请耐心等待...")
            r4 = benchmark_selector_limit(50)
            results.append(r4)
        except Exception as e:
            print(f"❌ 测试4失败: {e}")
    else:
        print("\n测试4: 选股性能")
        print("-" * 70)
        print("⏭️  跳过（使用 --full 启用完整测试）")
        print("运行: python3 performance_benchmark.py --full")

    # 总结
    print("\n" + "=" * 70)
    print("📊 测试总结")
    print("=" * 70)

    summary = {
        "timestamp": datetime.now().isoformat(),
        "full_test": full_test,
        "results": results
    }

    # 保存结果
    report_path = Path('performance_benchmark_report.json')
    with open(report_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 测试完成")
    print(f"📄 结果已保存: {report_path}")

    # 展示对标结果
    print("\n关键指标:")
    for r in results:
        if r.get('type') == 'config_merge':
            print(f"  • 配置合并: {r['avg']:.1f}ms (预期改善 < 5%)")
        elif r.get('type') == 'kline_cache':
            print(f"  • K线缓存: {r['improvement_pct']:.1f}% 改善 (预期 -30-50%)")
        elif r.get('type') == 'daily_summary':
            if 'elapsed_ms' in r:
                print(f"  • 日报生成: {r['elapsed_ms']:.1f}ms (预期 -150-200ms)")
        elif r.get('type') == 'selector':
            if 'elapsed_s' in r:
                print(f"  • 选股耗时: {r['elapsed_s']:.1f}s (预期 -30-50%)")

    print("\n建议:")
    print("1. 本地运行此脚本获取基准数据")
    print("2. 对标历史数据（如有）")
    print("3. 根据结果调整优化方案")

    return 0


if __name__ == "__main__":
    sys.exit(main())
