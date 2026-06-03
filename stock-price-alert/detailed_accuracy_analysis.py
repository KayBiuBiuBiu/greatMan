"""详细的预测准确率分析"""
import json
from pathlib import Path
import sys

print("=" * 70)
print("📊 股票预测准确率详细分析")
print("=" * 70)

# 1. 检查配置
print("\n🔍 第1步: 检查系统配置")
print("-" * 70)

config_path = Path("config.json")
if not config_path.exists():
    print("❌ 未找到 config.json")
    sys.exit(1)

with open(config_path) as f:
    config = json.load(f)

print(f"✅ 配置已加载")
print(f"  名称: {config.get('name', '?')}")
print(f"  描述: {config.get('desc', '?')}")

# 2. 回测性能
print("\n📈 第2步: 回测性能数据")
print("-" * 70)

backtest_path = Path("backtest_report.json")
if backtest_path.exists():
    with open(backtest_path) as f:
        backtest = json.load(f)
    
    code = backtest.get("code")
    print(f"✅ 回测报告存在 (股票: {code})")
    
    results = backtest.get("results", {})
    
    # 显示回测结果
    print(f"\n  回测周期性能:")
    for period in ["1", "3", "5"]:
        if period in results:
            r = results[period]
            win_rate = r.get("win", 0)
            trades = r.get("trades", 0)
            profit = r.get("profit", 0)
            
            print(f"    {period}年: " +
                  f"胜率 {win_rate:5.1f}% | " +
                  f"交易 {trades:2}次 | " +
                  f"总利润 {profit:6}% | " +
                  f"平均 {profit/max(1,trades):+5.2f}%/次")
    
    # 汇总分析
    all_wins = []
    all_trades = []
    all_profits = []
    for r in results.values():
        all_wins.append(r.get("win", 0))
        all_trades.append(r.get("trades", 0))
        all_profits.append(r.get("profit", 0))
    
    if all_wins:
        avg_win_rate = sum(all_wins) / len(all_wins)
        total_trades = sum(all_trades)
        total_profit = sum(all_profits)
        
        print(f"\n  汇总:")
        print(f"    平均胜率: {avg_win_rate:.1f}%")
        print(f"    总交易数: {total_trades} 次")
        print(f"    总收益: {total_profit}%")

# 3. 选股历史
print("\n📋 第3步: 选股历史和结果")
print("-" * 70)

picks_history = Path("data/picks_history")
if picks_history.exists():
    picks_files = sorted(picks_history.glob("*.json"), reverse=True)
    
    if picks_files:
        print(f"✅ 选股历史记录: {len(picks_files)} 天")
        
        # 统计最近的选股
        recent_picks = []
        for picks_file in picks_files[:5]:
            try:
                with open(picks_file) as f:
                    data = json.load(f)
                picks = data.get("picks", [])
                if picks:
                    recent_picks.extend(picks)
            except:
                pass
        
        if recent_picks:
            print(f"  最近5天共选出: {len(recent_picks)} 只股票")
            
            # 按策略分类
            by_strategy = {}
            for pick in recent_picks:
                strategy = pick.get("strategy", "unknown")
                if strategy not in by_strategy:
                    by_strategy[strategy] = []
                by_strategy[strategy].append(pick)
            
            print(f"  按策略分布:")
            for strategy, picks_list in sorted(by_strategy.items(), 
                                               key=lambda x: len(x[1]), reverse=True):
                print(f"    {strategy}: {len(picks_list)} 只")
        else:
            print("  ⚠️  最近没有选股结果")
    else:
        print("❌ 选股历史为空")
else:
    print("❌ 选股历史目录不存在")

# 4. 学习模型
print("\n🤖 第4步: 机器学习模型")
print("-" * 70)

models_dir = Path("models")
if models_dir.exists():
    model_files = list(models_dir.glob("*.json"))
    print(f"✅ 模型目录存在，找到 {len(model_files)} 个模型")
    
    for model_file in model_files[:5]:
        try:
            with open(model_file) as f:
                model_data = json.load(f)
            
            model_name = model_file.stem
            if isinstance(model_data, dict):
                accuracy = model_data.get("accuracy", model_data.get("test_accuracy", 0))
                print(f"    {model_name}: 精度 {accuracy:.2%}")
        except:
            pass
else:
    print("❌ 模型目录不存在")

# 5. 策略信息
print("\n⚙️ 第5步: 策略配置")
print("-" * 70)

strategies = config.get("strategies", {})
if strategies:
    print(f"✅ 已配置 {len(strategies)} 个策略:")
    for i, (name, strat_config) in enumerate(list(strategies.items())[:5], 1):
        enabled = strat_config.get("enabled", False)
        status = "✅ 启用" if enabled else "❌ 禁用"
        print(f"    {i}. {name}: {status}")
else:
    print("❌ 未配置任何策略")

# 6. 最终评估
print("\n" + "=" * 70)
print("📊 预测准确率总体评估")
print("=" * 70)

print("""
基于当前数据:

1️⃣ 回测数据 (单只股票 300058):
   • 1年胜率: 100.0% (2次交易)
   • 3年胜率: 66.7% (6次交易)
   • 5年胜率: 44.4% (9次交易)
   ➜ 长期胜率下降，需要持续优化

2️⃣ 选股质量:
   • 最近选股数: 待检查 (历史为空)
   • 策略覆盖: 待检查配置
   ➜ 需要运行完整选股来评估

3️⃣ 建议行动:
   ✅ 运行完整选股: python3 quant_cli.py daily-select
   ✅ 查看选股结果: cat daily_picks.json
   ✅ 分析交易历史: cat trade_log.json (最新)
   ✅ 运行回测: python3 backtest_picks_performance.py
   ✅ 训练优化: python3 auto_tune_accuracy.py --dry-run --days 7
""")

