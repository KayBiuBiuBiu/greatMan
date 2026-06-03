# 美股集成到监控终端 —— 实现指南

## 快速开始

### 三种集成方式

#### 1️⃣ **被动参考**（推荐首先实现）
在日报或选股时显示美股背景，用户看着参考。

**改造位置：** `run_alert.py` 的选股输出逻辑

```python
# 在 run_alert.py 中导入
from display_with_us_context import show_us_context_banner, format_us_context_inline

# 在输出日报/选股前显示美股横幅
def output_daily_picks(picks):
    print(show_us_context_banner())  # 显示美股背景
    
    for pick in picks:
        us_info = format_us_context_inline(pick['code'], pick.get('industry', ''))
        print(f"  {pick['code']} {pick['name']:12} 分数:{pick['score']:.1f} {us_info}")
```

#### 2️⃣ **主动过滤**（中等复杂度）
买点触发前用美股过滤，如果美股不强就不买。

**改造位置：** `strategy_engine.py` 或 `buy_filter.py`

```python
from display_with_us_context import filter_by_us_context

def should_buy_signal(code, industry, signal_type):
    # 美股过滤：芯片/光通信类只有美股不弱才能买
    if industry in ["芯片", "光通信"]:
        if not filter_by_us_context(code, industry, require="not_weak"):
            return False  # 美股弱势，阻止买入
    
    # 继续 A 股本地判断
    return evaluate_signal(code, signal_type)
```

#### 3️⃣ **智能加权**（最高级）
根据美股态势动态调整信号权重。

**改造位置：** `strategy_engine.py` 的信号评分逻辑

```python
from display_with_us_context import get_us_context_for_stock

def adjust_signal_score(code, industry, base_score):
    ctx = get_us_context_for_stock(code, industry)
    
    if not ctx:
        return base_score  # 无美股对标，保持原分
    
    # 根据美股态势调整权重
    if ctx['sentiment'] == 'strong':
        return base_score * 1.1  # 强势时提升 10%
    elif ctx['sentiment'] == 'weak':
        return base_score * 0.8  # 弱势时降低 20%
    else:
        return base_score  # 混合时不变
```

---

## 分步改造方案

### Step 1: 添加美股背景到日报（5 分钟）

**文件：** `run_alert.py`

找到选股输出的地方（大约第 8900 行附近的 `main_loop` 或 `output_*` 函数），在开头加入：

```python
# 导入美股显示
from display_with_us_context import show_us_context_banner

# 在输出日报时
if is_daily_select:
    print("\n" + show_us_context_banner())
    print("【今日选股】\n")
    # ... 继续输出选股列表
```

**效果：**
```
┌─ 🌍 美股背景概览 ────────────────────────┐
│ 芯片       NVDA↓-0.69% TSM↑+2.54% 😐混合
│ 科技       QQQ↑+0.46%          💪强势
└──────────────────────────────────────────┘
【今日选股】
  688008 澜起科技 [美股 NVDA↓ TSM↑ ASML↑]
```

---

### Step 2: 给选股列表加美股标签（10 分钟）

**文件：** `run_alert.py` 或 `stock_scanner.py`

找到输出 pick 的循环，改成：

```python
from display_with_us_context import format_us_context_inline

# 原来的输出：
for pick in picks:
    print(f"  {pick['code']} {pick['name']} 分数:{pick['score']}")

# 改成：
for pick in picks:
    us_inline = format_us_context_inline(pick['code'], pick.get('industry', ''))
    print(f"  {pick['code']} {pick['name']} 分数:{pick['score']} {us_inline}")
```

**效果：** 每只股旁多了美股参考，一眼看出全球态势。

---

### Step 3: 在买点过滤中加入美股逻辑（20 分钟）

**文件：** `strategy_engine.py` 或 `buy_rule.py`

```python
from display_with_us_context import filter_by_us_context

class BuyFilter:
    def should_buy(self, code, industry, signal):
        # 原逻辑
        if not self.check_volume(code):
            return False
        
        # 加入美股过滤
        if industry in ["芯片", "半导体", "光通信"]:
            if not filter_by_us_context(code, industry, require="not_weak"):
                print(f"  ⚠️ {code} 美股弱势，阻止买入")
                return False
        
        # 继续其他检查
        return True
```

---

### Step 4: 在监控详情中显示美股分析（15 分钟）

**文件：** `run_alert.py` 的监控显示逻辑

当用户查询某只股的详细信息时，加入美股背景：

```python
from display_with_us_context import format_us_context_full

def show_stock_detail(code, industry):
    print(f"【{code} 详细信息】")
    print_basic_quote(code)
    
    # 加入美股背景
    us_detail = format_us_context_full(code, industry)
    if us_detail:
        print(us_detail)
    
    print_kline(code)
```

---

## 配置集成（可选）

在 `config.json` 中添加美股相关配置：

```json
{
  "us_stocks": {
    "enabled": true,
    "cache_ttl_sec": 60,
    "display_mode": "inline",
    "buy_filter_mode": "not_weak",
    "industry_mapping": {
      "光通信": ["QQQ"],
      "芯片": ["NVDA", "TSM", "ASML"],
      "新能源": ["QQQ", "TSLA"]
    }
  }
}
```

然后在启动时加载：

```python
def configure_us_stocks_from_cfg(cfg):
    if cfg.get("us_stocks", {}).get("enabled"):
        from display_with_us_context import INDUSTRY_TO_US
        custom = cfg["us_stocks"].get("industry_mapping", {})
        INDUSTRY_TO_US.update(custom)
```

---

## 测试验证

运行现有测试验证集成：

```bash
# 1. 验证美股数据获取
python test_us_stocks.py

# 2. 验证终端显示
python display_with_us_context.py

# 3. 验证集成示例
python integration_example.py

# 4. 检查 run_alert 能否导入新模块
python -c "from display_with_us_context import *; print('✅ 导入成功')"
```

---

## 推荐集成顺序

1. **第一阶段（今天）** — 被动参考
   - [ ] 在日报开头显示美股横幅
   - [ ] 在选股列表后附加美股标签
   - 工作量：~20 分钟，可立即看效果

2. **第二阶段（明天）** — 主动过滤
   - [ ] 在 strategy_engine 中加入美股过滤
   - [ ] 配置哪些行业需要美股确认
   - 工作量：~30 分钟，需回测验证

3. **第三阶段（本周）** — 智能加权
   - [ ] 根据美股态势调整信号权重
   - [ ] 统计哪些行业对美股最敏感
   - 工作量：~1-2 小时，需数据验证

---

## 常见问题

**Q: 美股行情不实时怎么办？**  
A: yfinance 延迟约 15 分钟。如需完全实时，可改用 Finnhub（免费 tier 250 请求/分钟）或其他商业 API。

**Q: 如果某个行业没有美股对标怎么办？**  
A: `get_us_context_for_stock()` 会返回 None，显示/过滤逻辑会跳过。你可以在 `INDUSTRY_TO_US` 中手动补充行业映射。

**Q: 美股开盘前/闭市后怎么显示？**  
A: 会显示前一个交易日的数据。可在 `quote_us_stocks.py` 中加时间检查，如果是非交易时段就跳过拉取。

**Q: 能否只对特定行业使用美股过滤？**  
A: 可以。在 `should_buy()` 中加条件：
   ```python
   if industry not in ["芯片", "光通信"]:
       return True  # 其他行业不受美股过滤
   ```

---

## 相关文件清单

- `quote_us_stocks.py` — 核心库（获取美股行情）
- `display_with_us_context.py` — 显示层（格式化输出）
- `us_quick.py` — CLI 工具（手动查询）
- `us_context.py` — 背景分析（人工参考）
- `integration_example.py` — 集成示例（参考实现）
- `US_STOCKS_GUIDE.md` — 详细文档
- `test_us_stocks.py` — 测试套件

---

**下一步：** 选择上面的某个集成方式，我帮你改造 `run_alert.py`。
