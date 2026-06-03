# 🎯 10交易日短期交易优化方案

**时间**：2026-06-03  
**目标**：将短期交易胜率从 100% (2样本) 提升到 70%+ (真实数据验证)  
**交易周期**：3-10交易日

---

## 📊 当前系统分析

### 现状

```
✅ 优势:
  • 选股框架完整
  • 全市场 4904 只数据可用
  • 回测基础设施完善
  • K线缓存性能优秀 (89.7% 改善)

❌ 问题:
  • 没有短期专用策略
  • 风控参数全为 0 (没有止损/止盈)
  • 缺少日内技术指标 (MACD、RSI等)
  • 没有明确的进出点定义
  • 样本量极少 (只有2次交易)
```

---

## 🚀 3步优化方案

### 第1步：定义10日交易的进出规则

#### 进场规则（什么时候买）

```python
# 1️⃣ 技术面确认
买入条件 = (
    "日线 5日/10日均线金叉"  # 短期均线走强
    AND "RSI 低于 30"         # 超卖反弹机会
    AND "成交量突破"          # 有资金推动
    AND "股价在关键支撑上方"  # 不是跌到底
)

# 2️⃣ 量能确认
成交量确认 = (
    "换手率突增"              # 相比前5日平均
    AND "大宗交易或机构净流入" # 主力参与
)

# 3️⃣ 风险确认
风险检查 = (
    "不在重大利空前"          # 避开黑天鹅
    AND "股价不在历史高位"    # 避免被套
    AND "没有退市风险"        # 基本安全
)
```

**简单版进场**（立即可用）：
```
✅ 买入时机:
  1. 日线 5日均线在 10日均线上方（均线走强）
  2. RSI(14) < 35（相对超卖）
  3. 成交量相比前5日平均量 > 1.5倍
  4. 股价 > 20日均线 10% 以内（不太高）
```

#### 出场规则（什么时候卖）

```python
# 止盈规则
如果 (当前价格 - 买入价格) / 买入价格 >= 3%:
    卖出("达到止盈 +3%")

如果 (当前价格 - 买入价格) / 买入价格 >= 5%:
    卖出("达到止盈 +5%, 坚决出局不贪心")

# 止损规则
如果 (当前价格 - 买入价格) / 买入价格 <= -2%:
    卖出("止损 -2%, 保护本金")

如果 (当前价格 - 买入价格) / 买入价格 <= -3%:
    卖出("止损 -3%, 必须出局")

# 时间规则
如果 持仓天数 >= 10:
    卖出("10日到期, 无条件平仓")

如果 持仓天数 >= 15:
    卖出("超过目标周期，必须卖")

# 技术面反转规则
如果 5日均线 < 10日均线:
    卖出("均线转弱，避免反转亏损")
```

**简单版出场**（立即可用）：
```
✅ 卖出时机:
  1. 赚3% - 立即卖 (不贪)
  2. 赚5% - 一定要卖 (落袋为安)
  3. 亏2% - 止损卖 (保护本金)
  4. 10天还没赚 - 卖 (时间价值消退)
```

---

### 第2步：实现短期交易策略

#### 需要添加的技术指标

**文件：`quant_core/short_term_strategy.py`**（新建）

```python
"""10交易日短期交易策略"""
import pandas as pd
import numpy as np

class ShortTermTradingSignal:
    """10日交易的进出信号生成器"""
    
    @staticmethod
    def get_entry_signal(df: pd.DataFrame) -> bool:
        """判断是否应该买入
        
        Args:
            df: K线数据，至少包含 50 行
            
        Returns:
            True 表示可以买入，False 表示不买
        """
        if len(df) < 20:
            return False
        
        # 1. 均线金叉检查
        ma5 = df['close'].rolling(5).mean()
        ma10 = df['close'].rolling(10).mean()
        
        # 5日均线穿过10日均线（金叉）
        golden_cross = (ma5.iloc[-2] <= ma10.iloc[-2]) and (ma5.iloc[-1] > ma10.iloc[-1])
        
        if not golden_cross:
            return False
        
        # 2. RSI 超卖检查
        rsi = ShortTermTradingSignal.calculate_rsi(df['close'], period=14)
        rsi_oversold = rsi.iloc[-1] < 35  # RSI 低于 35 表示超卖
        
        if not rsi_oversold:
            return False
        
        # 3. 成交量确认
        volume_avg_5d = df['volume'].tail(6)[:-1].mean()  # 前5天的平均量
        volume_today = df['volume'].iloc[-1]
        
        volume_surge = volume_today > volume_avg_5d * 1.5
        
        if not volume_surge:
            return False
        
        # 4. 价格位置检查 (不能太高)
        ma20 = df['close'].rolling(20).mean().iloc[-1]
        price_today = df['close'].iloc[-1]
        
        price_not_too_high = price_today < ma20 * 1.1  # 不超过20日均线 10%
        
        return price_not_too_high
    
    @staticmethod
    def get_exit_signal(entry_price: float, current_price: float, 
                       days_held: int, df: pd.DataFrame) -> tuple:
        """判断是否应该卖出
        
        Returns:
            (should_exit, reason) - (是否卖出, 卖出原因)
        """
        profit_pct = (current_price - entry_price) / entry_price * 100
        
        # 止盈规则
        if profit_pct >= 5:
            return True, f"止盈 +5%, 落袋为安"
        
        if profit_pct >= 3:
            return True, f"止盈 +3%, 立即卖出"
        
        # 止损规则
        if profit_pct <= -3:
            return True, f"止损 -3%, 必须保护本金"
        
        if profit_pct <= -2:
            return True, f"止损 -2%, 防止继续下跌"
        
        # 时间规则
        if days_held >= 10:
            return True, "10日到期，无条件平仓"
        
        # 技术面反转（均线转弱）
        if len(df) >= 10:
            ma5 = df['close'].rolling(5).mean()
            ma10 = df['close'].rolling(10).mean()
            
            if ma5.iloc[-1] < ma10.iloc[-1]:
                return True, "均线转弱，避免反转亏损"
        
        return False, "继续持仓"
    
    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """计算 RSI 指标"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
```

---

### 第3步：配置风控参数

**文件：`config.json` 中的风控部分**

```json
{
  "risk_control": {
    "short_term_trading": {
      "enabled": true,
      "description": "10交易日短期交易专用风控",
      
      "position_sizing": {
        "max_total_position_pct": 50,
        "comment": "最多用 50% 资金做短期交易"
      },
      
      "per_trade": {
        "max_position_pct": 10,
        "comment": "每只股票最多 10% 资金（5只同时持仓）"
      },
      
      "loss_control": {
        "stop_loss_pct": -2.0,
        "comment": "亏损 2% 时止损"
      },
      
      "profit_taking": {
        "take_profit_target1": 3.0,
        "take_profit_target2": 5.0,
        "comment": "+3% 时可以出，+5% 时必须出"
      },
      
      "time_limit": {
        "max_hold_days": 10,
        "comment": "10天后无条件平仓"
      }
    }
  }
}
```

---

## 📈 预期效果

### 短期目标（这周）

```
目前: 1年胜率 100% (2样本，不可信)
目标: 这周实际交易 10-15 次
预期: 胜率 70-75% (用真实数据验证)

如果能达到:
  • 10 次交易，7 次赢，3 次亏
  • 平均收益: (+3% × 7 + (-2%) × 3) / 10 = 1.8% 每周
  • 周年化: 1.8% × 52 ≈ 94% (理论值，实际会低)
```

### 中期目标（这月）

```
积累数据: 30-50 次交易
分析效果: 
  • 真实胜率 (>60% 表示有效)
  • 平均持仓时间 (应该 5-8 天)
  • 最大回撤 (应该 <5%)
  • 风险收益比 (应该 >1:2)

调整参数:
  • 如果胜率 <60%，优化进场条件
  • 如果经常止损，放松止损点到 -3%
  • 如果收益不够，提高止盈目标到 5-8%
```

---

## 🛠️ 实现步骤

### 今天（第1天）

```bash
# 1. 创建短期交易策略文件
cat > quant_core/short_term_strategy.py << 'EOF'
[上面的代码]
EOF

# 2. 测试策略逻辑
python3 << 'PYEOF'
from quant_core.short_term_strategy import ShortTermTradingSignal
from quant_core.selector import load_df

# 随机选一只股票测试
df = load_df("600711", lookback=50)
entry = ShortTermTradingSignal.get_entry_signal(df)
print(f"进场信号: {entry}")

# 测试止盈止损
exit_flag, reason = ShortTermTradingSignal.get_exit_signal(
    entry_price=12.50,
    current_price=12.87,
    days_held=3,
    df=df
)
print(f"卖出信号: {exit_flag}, 原因: {reason}")
PYEOF

# 3. 更新配置
vim config.json
# 添加上面的短期交易风控配置

# 4. 运行当天选股
python3 quant_cli.py daily-select
```

### 本周（第2-5天）

```bash
# 每天追踪推荐的股票
# 记录:
#   - 推荐时的价格
#   - 买入时的价格和时间
#   - 卖出时的价格和时间
#   - 实际收益率
#   - 是否按规则执行

# 生成每日交易记录
python3 << 'PYEOF'
import json
from datetime import datetime

trading_record = {
    "date": datetime.now().strftime("%Y-%m-%d"),
    "trades": [
        {
            "code": "600711",
            "entry_price": 12.50,
            "entry_date": "2026-06-03",
            "exit_price": 12.87,
            "exit_date": "2026-06-06",
            "profit_pct": (12.87 - 12.50) / 12.50 * 100,
            "days_held": 3,
            "reason": "止盈 +3%"
        }
    ]
}

with open(f"trading_records_{datetime.now().strftime('%Y%m%d')}.json", 'w') as f:
    json.dump(trading_record, f, indent=2)
PYEOF
```

### 本月（后续优化）

```bash
# 周末分析一周的交易
python3 << 'PYEOF'
# 统计这周的:
#  - 总交易次: ?
#  - 赢家: ?
#  - 亏家: ?
#  - 胜率: ?%
#  - 总收益: ?%
#  - 平均收益/次: ?%

# 根据结果调整参数
PYEOF
```

---

## 💡 关键参数调优表

| 参数 | 初始值 | 偏低调整 | 偏高调整 | 说明 |
|------|--------|---------|---------|------|
| 止盈1 | +3% | +2% | +4% | 前期保证赚，后期可提 |
| 止盈2 | +5% | +4% | +6% | 贪心目标，不一定能到 |
| 止损 | -2% | -1% | -3% | 保护本金，严格执行 |
| 持仓天数 | 10天 | 8天 | 15天 | 根据实际持仓时间调 |
| RSI阈值 | 35 | 30 | 40 | 更激进/保守的进场 |
| 成交量倍数 | 1.5倍 | 1.3倍 | 2.0倍 | 确保有资金推动 |

---

## 📋 评估标准

### 一周后应该达到的指标

```
✅ 交易数: ≥ 10 次
✅ 胜率: ≥ 60% (≥6/10 赢)
✅ 平均收益: ≥ 1.5% 每周
✅ 最大单次亏损: ≤ -2.5%
✅ 最大连续亏损: ≤ 2 次

如果没达到:
❌ 交易太少 → 放松进场条件，或增加选股数量
❌ 胜率太低 → 优化进场条件，加强技术面要求
❌ 收益不够 → 提高止盈目标，或增加头寸
❌ 亏损过大 → 降低止损点，或减小头寸
```

---

## 🎯 总结

### 为什么这个方案有效？

```
1️⃣ 高频交易
   • 10日周期增加交易机会
   • 更多样本验证策略有效性
   • 快速反馈和优化

2️⃣ 明确规则
   • 自动进出，不靠感觉
   • 严格止损，保护本金
   • 坚决止盈，避免贪心

3️⃣ 风险可控
   • 每笔最多亏 2-3%
   • 头寸大小有限制
   • 时间上有截止点

4️⃣ 数据驱动
   • 一周就有 10+ 样本
   • 一月就有 40+ 样本
   • 足够验证真实胜率
```

### 立即可开始

```
✅ 不需要等待
✅ 使用现有选股框架
✅ 只需添加风控和策略
✅ 一周内就能看到结果
```

---

**下一步**：今天立即创建 `short_term_strategy.py`，从本周开始用新规则交易。

生成时间：2026-06-03 16:45
