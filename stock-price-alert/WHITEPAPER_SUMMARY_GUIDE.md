# 【大白话日报标签】集成指南

## 🎯 核心功能

每只股下面加一条标签，用大白话告诉你：**昨晚美股这个板块涨不涨，期货涨不涨**

### 效果对比

**改造前：**
```
002110 盛屯矿业 $8.50 📈+1.20%
→ 只知道 A 股涨了，不知道全球咋样
```

**改造后：**
```
002110 盛屯矿业 $8.50 📈+1.20%
   └→ 昨晚全球态势：📦 铜价↓-0.93% | 💔 偏弱，谨慎
→ 一眼看出：A 股涨但铜价跌，全局偏弱，要谨慎！
```

---

## 📦 新增文件

- `daily_sector_summary.py` — 核心模块，生成大白话标签
- `whitepaper_summary_demo.py` — 完整演示效果

---

## 🔧 改造方案

### 改造 1：在日报选股中加标签（最重要）

**文件：** `run_alert.py` 或 `quant_cli.py` 的日报输出

**改造前：**
```python
for pick in quality_picks:
    print(f"  {pick['code']} {pick['name']} 分数:{pick['score']}")
```

**改造后：**
```python
from daily_sector_summary import format_stock_with_sector_summary

for pick in quality_picks:
    # 获取第一行：基本信息
    display = format_stock_with_sector_summary(
        pick['code'],
        pick['name'],
        pick.get('industry', ''),  # 板块
        pick['price'],
        pick['change_pct'],
    )
    # 显示（自动包含两行：基本信息 + 全球态势）
    print(display)
```

**工作量：** 5 行代码

---

### 改造 2：在监控显示中加标签（每次盘中看）

**文件：** `run_alert.py` 的 watch_pack 显示

**改造前：**
```python
for code in watch_codes:
    quote = get_quote(code)
    print(f"  {code} ${quote['price']:.2f} {quote['chg_pct']:+.2f}%")
```

**改造后：**
```python
from daily_sector_summary import format_stock_with_sector_summary

for code in watch_codes:
    quote = get_quote(code)
    industry = stock_industry.get(code, '')  # 从某个地方获取板块
    
    display = format_stock_with_sector_summary(
        code,
        stock_name.get(code, ''),
        industry,
        quote['price'],
        quote['change_pct'],
        holdings.get(code, 0),  # 持仓数
    )
    print(display)
```

**工作量：** 8 行代码

---

### 改造 3：在详细分析中加标签（查看单只股时）

**文件：** `run_alert.py` 或专用查询函数

```python
from daily_sector_summary import get_sector_daily_summary

def show_stock_detail(code, name, industry):
    """查看单只股的详细信息。"""
    quote = get_quote(code)
    
    print(f"【{code} {name}】")
    print(f"现价：${quote['price']:.2f} {quote['change_pct']:+.2f}%")
    
    # 新增：显示全球态势
    summary = get_sector_daily_summary(code, industry)
    if summary:
        print(f"昨晚全球态势：{summary}")
    
    # ... 其他信息 ...
```

**工作量：** 5 行代码

---

## 💡 核心逻辑

### 板块映射配置

在 `daily_sector_summary.py` 中定义了各板块的美股对标和商品期货映射：

```python
SECTOR_CONTEXT = {
    "有色金属": {
        "us_stocks": [],           # 没有直接对标美股
        "commodities": ["copper"], # 看铜期货
        "zh_name": "有色金属",
    },
    "芯片": {
        "us_stocks": ["NVDA", "TSM", "ASML"],  # 看这几个美股
        "commodities": [],                      # 没有商品期货
        "zh_name": "芯片",
    },
    "新能源汽车": {
        "us_stocks": ["TSLA", "QQQ"],  # 看特斯拉和纳指
        "commodities": [],
        "zh_name": "新能源汽车",
    },
    # ... 更多板块 ...
}
```

### 判断逻辑

生成的标签会自动判断：

```
💚 很强势    avg_pct > 1.0%     （绿心：可加仓）
💙 偏强      0.2% < avg_pct ≤ 1.0%   （蓝心：可考虑）
💛 混合      -0.2% < avg_pct ≤ 0.2%  （黄心：观望）
💔 偏弱      -1.0% < avg_pct ≤ -0.2% （红心：谨慎）
💀 很弱      avg_pct ≤ -1.0%         （骷髅：减仓）
```

---

## 🚀 立即体验

```bash
# 看演示效果（最直观）
python whitepaper_summary_demo.py

# 看单个函数的使用
python daily_sector_summary.py
```

---

## 📝 配置修改

如果你要针对特定板块调整，编辑 `daily_sector_summary.py` 中的 `SECTOR_CONTEXT`：

**添加新板块：**
```python
"你的板块名": {
    "us_stocks": ["美股代码1", "美股代码2"],
    "commodities": ["commodity1"],
    "zh_name": "显示名称",
},
```

**修改现有板块：**
- 改 `us_stocks` 列表改变美股对标
- 改 `commodities` 列表改变商品关联

---

## 💻 代码集成示例

### 最简单的用法：

```python
from daily_sector_summary import format_stock_with_sector_summary

# 生成完整的两行显示
display = format_stock_with_sector_summary(
    code="002110",
    name="盛屯矿业",
    sector="有色金属",
    price=8.50,
    chg_pct=1.2,
    shares=5000,
)
print(display)

# 输出：
# 002110 盛屯矿业 | 现价 $8.50 📈+1.20% | 持仓 5000股
#    └→ 昨晚全球态势：📦 铜价↓-0.93% | 💔 偏弱，谨慎
```

### 只获取标签（不要完整行）：

```python
from daily_sector_summary import get_sector_daily_summary

summary = get_sector_daily_summary(code="002110", sector="有色金属")
print(f"全球态势：{summary}")

# 输出：
# 全球态势：📦 铜价↓-0.93% | 💔 偏弱，谨慎
```

---

## ⚡ 建议改造顺序

### TODAY（立即，5 分钟）
```bash
python whitepaper_summary_demo.py
# 看一遍效果，理解大白话标签的价值
```

### TOMORROW（明天，10 分钟）
- 改造日报选股输出（改造 1）
- 这样每天盘前就能看到全局态势标签

### THIS WEEK（本周，20 分钟）
- 改造监控显示（改造 2）
- 盘中每看一只持仓，都能看到全球态势

### NEXT（可选，5 分钟）
- 改造详细分析查询（改造 3）
- 点击查看单只股时显示标签

---

## 🎯 效果验证清单

集成完成后，检查：

- [ ] 日报选股时每只股下面显示「昨晚全球态势」
- [ ] 标签显示美股涨跌和商品涨跌
- [ ] 标签最后有综合判断（💚💙💛💔💀）
- [ ] 持仓监控时每只股下面也有标签
- [ ] 标签能实时更新（反映最新的美股+期货数据）

---

## 📊 显示效果检查表

| 持仓情况 | 预期标签 | 行动 |
|--------|--------|-----|
| A↑ 美↑ 期↑ | 💚很强 | ✅ 加仓 |
| A↑ 美↓ 期↓ | 💔偏弱 | 🟡 观望 |
| A↓ 美↑ 期↑ | 💚很强 | 💚 补仓 |
| A↓ 美↓ 期↓ | 💀很弱 | 🔴 减仓 |

---

## ✨ 核心价值

不需要你自己去查 5 个地方综合判断，一条标签直接告诉你：

```
✅ 美股昨晚涨还是跌
✅ 期货昨晚涨还是跌
✅ 总体是强还是弱
✅ 应该加仓还是减仓
```

**大白话，秒懂！**

---

## 下一步

准备好改造 `run_alert.py` 了吗？
- 我可以直接改造
- 或者给你改造后的代码片段自己加

怎么选？
