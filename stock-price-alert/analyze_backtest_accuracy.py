"""分析回测准确率"""
import json
from pathlib import Path
from collections import defaultdict

# 收集所有回测数据
backtest_data = []

# 1. 主backtest报告
backtest_path = Path("backtest_report.json")
if backtest_path.exists():
    with open(backtest_path) as f:
        data = json.load(f)
    print(f"📊 backtest_report.json 数据:")
    print(f"  股票: {data.get('code')}")
    for period, results in data.get("results", {}).items():
        print(f"    {period}年: 胜率 {results.get('win', 0):.1f}%, " +
              f"交易 {results.get('trades', 0)}次, " +
              f"利润 {results.get('profit', 0)}")

# 2. 查找其他回测文件
backtest_dir = Path(".")
backtest_files = list(backtest_dir.glob("*backtest*.json")) + \
                 list(backtest_dir.glob("*performance*.json")) + \
                 list(backtest_dir.glob("*test*.json"))

print(f"\n📁 找到的回测相关文件:")
for f in backtest_files[:10]:
    print(f"  {f.name}")

# 3. 检查 daily_picks 历史
picks_history = Path("data/picks_history")
if picks_history.exists():
    picks_files = sorted(picks_history.glob("*.json"), reverse=True)
    print(f"\n📋 选股历史 ({len(picks_files)} 天):")
    
    # 统计最近的选股结果
    all_picks = defaultdict(list)
    for picks_file in picks_files[:7]:  # 最近7天
        try:
            with open(picks_file) as f:
                data = json.load(f)
            date = picks_file.stem
            picks = data.get("picks", [])
            print(f"  {date}: {len(picks)} 只股票")
            for pick in picks[:3]:
                code = pick.get("code", "?")
                print(f"    - {code} (得分 {pick.get('score', 0):.1f})")
        except:
            pass

# 4. 检查策略配置
config_path = Path("config.json")
if config_path.exists():
    with open(config_path) as f:
        config = json.load(f)
    
    print(f"\n⚙️ 策略配置:")
    
    # 策略信息
    strategies = config.get("strategies", {})
    print(f"  已启用策略: {len(strategies)} 个")
    for name, strat in list(strategies.items())[:5]:
        print(f"    - {name}")
    
    # 风控信息
    risk = config.get("risk_control", {})
    print(f"\n🛡️ 风险控制:")
    print(f"  最大单只持仓: {risk.get('max_position_pct', 0):.1f}%")
    print(f"  最大总持仓: {risk.get('max_total_position_pct', 0):.1f}%")
    print(f"  止损点: {risk.get('stop_loss_pct', 0):.1f}%")
    print(f"  止盈点: {risk.get('take_profit_pct', 0):.1f}%")

# 5. 查看 ML 模型信息
ml_forward4_path = Path("models/ml_forward4.json")
if ml_forward4_path.exists():
    with open(ml_forward4_path) as f:
        ml_data = json.load(f)
    print(f"\n🤖 ML Forward4 模型:")
    print(f"  模型版本: {ml_data.get('version', '?')}")
    print(f"  训练样本: {ml_data.get('train_samples', 0)}")
    print(f"  训练精度: {ml_data.get('train_accuracy', 0):.2%}")
    print(f"  验证精度: {ml_data.get('val_accuracy', 0):.2%}")
    print(f"  测试精度: {ml_data.get('test_accuracy', 0):.2%}")

