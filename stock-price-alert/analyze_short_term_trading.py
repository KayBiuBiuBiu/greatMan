"""分析短期交易（10天左右）的表现"""
import json
from pathlib import Path
from collections import defaultdict

print("=" * 70)
print("📊 10交易日短期交易 - 详细分析")
print("=" * 70)

# 1. 检查当前策略配置
print("\n🔍 第1步: 检查短期交易策略配置")
print("-" * 70)

config_path = Path("config.json")
if config_path.exists():
    with open(config_path) as f:
        config = json.load(f)
    
    # 检查策略参数
    strategies = config.get("strategies", {})
    print(f"已配置策略: {len(strategies)} 个")
    
    # 查看 K-line 参数
    kline_store = config.get("kline_store", {})
    print(f"\nK线配置:")
    print(f"  启用: {kline_store.get('enabled', False)}")
    
    # 查看选股参数
    selector = config.get("selector", {})
    print(f"\n选股参数:")
    for key in ["min_price", "max_price", "min_vol", "max_vol"]:
        val = selector.get(key)
        if val:
            print(f"  {key}: {val}")
    
    # 查看风控
    risk = config.get("risk_control", {})
    print(f"\n风控配置:")
    print(f"  最大持仓: {risk.get('max_total_position_pct', 0)}%")
    print(f"  单只限制: {risk.get('max_position_pct', 0)}%")
    print(f"  止损: {risk.get('stop_loss_pct', 0)}%")
    print(f"  止盈: {risk.get('take_profit_pct', 0)}%")

# 2. 分析回测数据
print("\n" + "=" * 70)
print("📈 第2步: 回测数据分析")
print("-" * 70)

backtest_path = Path("backtest_report.json")
if backtest_path.exists():
    with open(backtest_path) as f:
        backtest = json.load(f)
    
    results = backtest.get("results", {})
    
    # 分析 1年的短期交易
    if "1" in results:
        r = results["1"]
        print(f"\n1年周期回测 (最接近短期):")
        print(f"  胜率: {r.get('win', 0):.1f}%")
        print(f"  交易次: {r.get('trades', 0)}")
        print(f"  总利润: {r.get('profit', 0)}%")
        
        trades = r.get('trades', 1)
        win_pct = r.get('win', 0)
        avg_profit = r.get('profit', 0) / max(1, trades)
        
        print(f"\n推导数据:")
        print(f"  赢家交易数: {int(trades * win_pct / 100)}")
        print(f"  亏家交易数: {int(trades * (100 - win_pct) / 100)}")
        print(f"  平均收益/次: {avg_profit:.2f}%")
        
        # 但这只有2次，样本太少
        print(f"\n⚠️  样本量太少 (只有{trades}次)")
        print(f"   需要更多数据来评估10日交易的真实表现")

# 3. 查看交易日志中的10日周期
print("\n" + "=" * 70)
print("📋 第3步: 最近的交易记录")
print("-" * 70)

trade_log_path = Path("trade_log.json")
if trade_log_path.exists():
    with open(trade_log_path) as f:
        trades = json.load(f)
    
    print(f"交易记录: {len(trades)} 条")
    
    # 统计最近的交易
    if trades:
        print(f"\n最近10条交易信号:")
        for i, trade in enumerate(trades[:10], 1):
            time = trade.get("time", "?")
            code = trade.get("code", "?")
            signal = trade.get("signal", "")[:50]
            print(f"  {i}. {time} {code}")
            print(f"     信号: {signal}...")

# 4. 关键问题诊断
print("\n" + "=" * 70)
print("🔍 第4步: 短期交易的关键问题")
print("-" * 70)

print("""
当前系统可能的问题:

1️⃣ 信号质量问题
   ❌ 选股时机不当
   ❌ 进场信号不清晰
   ❌ 缺少短期技术指标

2️⃣ 持仓管理问题
   ❌ 没有明确的5-15日退出计划
   ❌ 止盈止损设置不合理
   ❌ 风控参数过松或过严

3️⃣ 策略匹配问题
   ❌ 中长期策略不适合10日交易
   ❌ 缺少日内或周内级别的指标
   ❌ 没有针对10日的优化

4️⃣ 数据问题
   ❌ 缺少分钟线数据
   ❌ 没有实时情绪指标
   ❌ 缺少短期成交量分析
""")

# 5. 建议方案
print("\n" + "=" * 70)
print("💡 第5步: 10日交易的优化方案")
print("-" * 70)

print("""
优化方向 (从高优先级到低):

【高优先】立即可做
  ✅ 强化短期技术指标
     - MACD 短期背离
     - RSI 超卖反弹
     - 5日/10日均线金叉
     - 成交量突破确认

  ✅ 设置明确的进出点
     - 进场: 技术突破 + 量能确认
     - 止盈: +3% ~ +5% 就出
     - 止损: -2% ~ -3% 出局

  ✅ 调整风控参数
     - 单次亏损限制: 2-3%
     - 单只头寸: 总资金的 5-10%
     - 同时持仓不超过 3-5 只

【中优先】这周完成
  ⚠️ 构建10日交易策略
     - 日内级别 (分钟线)
     - 周内情绪 (涨停/跌停)
     - 资金面 (主力跟踪)

  ⚠️ 回测短期策略
     - 10日周期的历史胜率
     - 平均持仓时间
     - 风险收益比

【低优先】持续优化
  ℹ️ 实时监控系统
     - 每日复盘成功率
     - 追踪关键信号的准确度
     - 优化参数

  ℹ️ 建立信号数据库
     - 记录每个信号的10日走势
     - 统计哪些信号最可靠
     - 持续改进
""")

print("\n" + "=" * 70)
print("🚀 核心建议")
print("=" * 70)

print("""
你的短期交易策略应该是:

1️⃣ 今天推荐好股票
   ↓
2️⃣ 明天或后天买入
   ↓
3️⃣ 3-10日内卖出
   ↓
4️⃣ 赚3-5%就走，亏2-3%就止损

关键是:
  • 信号必须高质量 (胜率 > 70%)
  • 进场点要清晰 (不是模糊的"可以买")
  • 出场要坚决 (达到目标就卖, 不贪心)
  • 风控要严格 (严格止损, 保护本金)

当前系统的问题:
  ❌ 没有针对10日的短期策略
  ❌ 没有明确的进出点定义
  ❌ 风控参数为空 (没有止损)
  ❌ 缺少日内级别的技术指标
  ❌ 没有3-10日的历史回测数据
""")

