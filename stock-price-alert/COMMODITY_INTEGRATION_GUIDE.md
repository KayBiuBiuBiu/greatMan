# 美股 + 商品期货 完整集成指南

## 🎯 核心场景：重仓盛屯矿业

你有 5000 股盛屯矿业，需要实时关注：
- **A 股本地**：公司技术面、基本面
- **美股参考**：全球经济态势（对金属价格影响）
- **商品期货**：铜价实时走向（盛屯的主要驱动因素）

### 集成后的效果

```
🚀 启动时看到：

┌─ 🌍 美股背景 ─────────────────────┐
│ 纳指 QQQ↑+0.46%  经济向好参考     │
└────────────────────────────────────┘

┌─ 📦 大宗商品 ─────────────────────┐
│ 铜价↓-1.01% $6.61/磅  盛屯有压力  │
└────────────────────────────────────┘

💎 重仓：盛屯矿业(002110)  5000股
```

```
⏰ 盘中监控时看到：

002110 盛屯矿业  现价 $8.50 📈+1.20%  浮盈 +510元
  └→ 商品: [铜价↓-1.01% $6.61]
      ✅ A股上涨，但铜价下跌 → 需要谨慎
      💡 如果铜价反弹，有更大上升空间
```

---

## 📦 新增文件清单

### 商品期货模块
- `quote_commodities.py` — 期货数据获取（COMEX 铜、铁矿石等）
- `display_commodities.py` — 期货显示和 A 股关联映射

### 综合集成
- `comprehensive_dashboard_demo.py` — 完整的综合终端演示

---

## 🔧 改造方案（基于之前的美股方案扩展）

### 改造 1：启动显示添加商品期货

**文件**：`run_alert.py` 的 `main()` 函数

```python
from display_with_us_context import show_us_context_banner
from display_commodities import show_commodities_overview  # 新增

def main() -> int:
    # ... 配置加载 ...
    
    print(show_us_context_banner())  # 美股背景
    print(show_commodities_overview())  # 新增：商品概览
    
    # ... 继续轮询 ...
```

**效果**：启动时同时看到美股和商品期货

---

### 改造 2：选股时附加商品关联

**文件**：`quant_cli.py` 或 `run_alert.py` 的日报输出

```python
from display_commodities import format_commodity_display

for pick in quality_picks:
    # 原来的显示...
    us_tag = format_us_context_inline(pick['code'], pick.get('industry', ''))
    print(f"  {pick['code']} {pick['name']} {us_tag}")
    
    # 新增：如果是商品相关的股，显示商品价格
    if pick['code'] == '002110':  # 盛屯矿业
        comm_tag = format_commodity_display('copper')
        print(f"       └→ 商品: {comm_tag}")
```

**效果**：选股时立即看到重仓股对应的商品价格

---

### 改造 3：监控显示加商品期货

**文件**：`run_alert.py` 的 watch_pack 显示

```python
from display_commodities import format_commodity_display

for code in watch_codes:
    quote = get_quote(code)
    us_ref = format_us_context_inline(code, stock_industry.get(code, ''))
    print(f"  {code} ${quote['price']:.2f} {us_ref}")
    
    # 新增：如果是商品相关股，显示商品背景
    if code == '002110':  # 盛屯矿业
        copper_tag = format_commodity_display('copper')
        print(f"       └→ 商品: {copper_tag}")
```

**效果**：持仓监控时看到商品期货联动

---

### 改造 4：决策支持加商品参考（可选高级）

**文件**：`strategy_engine.py` 的买卖决策

```python
from quote_commodities import get_commodity_price

def should_buy_shuntu(code):
    """盛屯矿业专项决策逻辑。"""
    # A 股本地信号
    a_stock_signal = evaluate_signal(code)
    if not a_stock_signal:
        return False
    
    # 商品参考：铜价太弱就先观望
    copper = get_commodity_price('copper')
    if copper and copper['change_pct'] < -2.0:
        print(f"⚠️  铜价大幅下跌 {copper['change_pct']:.2f}%，建议观望")
        return False
    
    return True
```

**效果**：买卖点时自动参考商品态势

---

## 💡 使用技巧

### 针对盛屯矿业的监控清单

每天开盘前检查：

```bash
# 1. 查看铜价 + 相关 A 股
python us_quick.py           # 看美股（参考全球经济）
python display_commodities.py # 看商品期货（直接看铜价）

# 2. 看综合效果
python comprehensive_dashboard_demo.py
```

### 决策框架

```
铜价 ↑ 美股 ↑  →  🟢 强看多    加仓盛屯
铜价 ↑ 美股 ↓  →  🟡 微看多    等待美股反弹
铜价 ↓ 美股 ↑  →  🟡 微看多    等待铜价反弹
铜价 ↓ 美股 ↓  →  🔴 看空     考虑减仓
```

### 特殊情况

**风险叠加**：
- 铜价下跌 + 美股弱势 + 盛屯技术面破位
  → 果断减仓，风险最大

**机会期**：
- 铜价底部 + 美股反弹 + 盛屯支撑位放量
  → 主动加仓，机会最大

---

## 📊 商品期货与 A 股的对应关系

| 商品 | 代码 | A 股对标 | 相关性 |
|-----|------|--------|-------|
| 铜 | HG=F | 盛屯矿业、紫金矿业、中国铝业 | 高正相关 |
| 铁矿石 | SI=F | 钢铁股、工程机械 | 中正相关 |
| 原油 | CL=F | 中国石油、海油工程 | 高正相关 |
| 黄金 | GC=F | 紫金矿业、招金矿业 | 中正相关 |

---

## 🚀 立即体验

```bash
# 看商品期货行情
python quote_commodities.py

# 看商品与 A 股的关联
python display_commodities.py

# 看完整的综合仪表板（最直观）
python comprehensive_dashboard_demo.py

# 看美股 + 商品的混合演示
python terminal_display_demo.py  # 然后手动加商品段
```

---

## 🎯 对比：改造前后

### 改造前（现状）
```
🚀 启动时：看不到美股背景，看不到商品价格
📊 选股时：不知道全球态势和原料价格
👁️ 监控时：持仓 5000 股盛屯，不知道铜价是涨是跌
🎯 决策时：只看本地信号，容易逆全球趋势
```

### 改造后
```
🚀 启动时：一眼看清美股、商品、行业态势
📊 选股时：盛屯后面直接看铜价，同步判断
👁️ 监控时：持仓行后面直接看 [铜价↓-1.01%]，实时联动
🎯 决策时：有全球视角，避免风险叠加
```

---

## ⚡ 快速集成步骤

### 最快方案（5 分钟）
1. 在 `run_alert.py` 的 `main()` 中加 2 行代码
2. 导入 `show_commodities_overview()`
3. 启动时就能看到商品期货

### 标准方案（20 分钟）
1. 改造启动显示（5 分钟）
2. 改造选股输出（8 分钟）
3. 改造监控显示（7 分钟）

### 完整方案（40 分钟）
1. 完成标准方案
2. 改造决策逻辑，加商品过滤
3. 自定义重仓股的商品映射

---

## 📝 配置自定义

在 `display_commodities.py` 中可以自定义：

```python
HEAVY_HOLDINGS = {
    "002110": {  # 你的重仓
        "name": "盛屯矿业",
        "commodities": ["copper"],  # 关联商品
        "role": "铜产业链参与者",
        "correlation": "高正相关",
    },
    # 添加你的其他重仓
}
```

---

## ✅ 验证清单

集成完成后，检查：

- [ ] 启动时看到美股背景横幅
- [ ] 启动时看到商品期货概览
- [ ] 选股列表后面看到 [美股 XXX] 标签
- [ ] 重仓股后面看到 [商品 XXX] 标签
- [ ] 监控时实时看到商品价格变化
- [ ] 铜价变化时立即在监控行看到

---

## 💬 常见问题

**Q: 铜价数据准确吗？**  
A: COMEX 铜期货是全球最主要的铜定价，数据实时且权威。yfinance 延迟约 15 分钟，对日间监控足够。

**Q: 如果只看美股不看商品可以吗？**  
A: 可以，但对于盛屯这样的商品股，商品价格是最直接的驱动，建议一起看。

**Q: 可以加其他商品吗？**  
A: 可以，在 `quote_commodities.py` 的 `COMMODITY_SYMBOLS` 中添加更多期货代码即可。

**Q: 商品价格和股价的关系什么时候最紧密？**  
A: 一般是开盘后 1-2 小时，商品开盘信息完全传导到 A 股。

---

## 下一步

建议按这个顺序：

1. **今天**：运行 `comprehensive_dashboard_demo.py` 看效果
2. **明天**：改造 `run_alert.py` 加启动显示（5 分钟）
3. **本周**：完整改造选股和监控显示（20 分钟）
4. **可选**：改造决策逻辑加商品过滤（进阶）

开始吧！🚀
