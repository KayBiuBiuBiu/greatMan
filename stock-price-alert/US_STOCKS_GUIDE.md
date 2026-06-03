# 美股行情集成指南

## 新增模块

### 1. `quote_us_stocks.py` — 美股行情核心库
- **`get_us_quote(symbol)`** — 获取单个美股实时行情
  - 支持代码：NVDA、TSM、ASML、QQQ、SPY 等
  - 返回：价格、涨跌幅、PE、市值等
  - 自动 60 秒缓存，可配置 TTL

- **`get_us_quotes_batch(symbols)`** — 批量获取多个美股行情
- **`get_us_kline(symbol, period, interval)`** — 获取美股 K 线数据
  - 支持 1d/5d/1mo/3mo/6mo/1y/max 周期
  
### 2. `us_quick.py` — 美股快速查询工具
快速命令行查询美股走势，用于日报或人工判断：
```bash
python us_quick.py              # 显示所有对标
python us_quick.py qqq          # 查看纳指
python us_quick.py nvda kline   # 查看 NVDA K 线
```

### 3. `us_context.py` — 美股背景上下文
在选股或买点判断前展示美股态势，支持：
- `show_us_context()` — 显示关键美股走向
- `us_context_for_buy_filter()` — 用于选股过滤的美股判断逻辑

## 关键美股对标

| 美股 | 名称 | A 股对标行业 | 作用 |
|-----|------|-----------|-----|
| QQQ | 纳斯达克 100 | 科技、新能源、互联网 | 整体科技态势 |
| SPY | 标普 500 | 大盘、消费、金融 | 美国大盘走向 |
| NVDA | 英伟达 | 芯片、AI | 芯片产业链强弱 |
| TSM | 台积电 | 芯片代工 | 全球芯片产能 |
| ASML | 阿斯麦 | 芯片设备 | 产业链上游 |
| TSLA | 特斯拉 | 新能源汽车 | 新能源热度 |
| XLV | 医疗健康 | 医药、医疗 | 医药板块参考 |
| XLI | 工业 | 机械、重工 | 重工板块参考 |

## 使用示例

### 例 1：查看纳指和 NVDA，判断芯片行业
```bash
$ python us_quick.py qqq
$ python us_quick.py nvda kline
```

### 例 2：在选股前检查美股背景
```bash
$ python us_context.py
# 根据输出决定是否调整选股策略
```

### 例 3：在 Python 代码中使用
```python
from quote_us_stocks import get_us_quote

# 检查纳指是否强势
qqq = get_us_quote("QQQ")
if qqq and qqq['change_pct'] > 0.5:
    print("美股科技走强，适合买入科技股")

# 批量查询
us_prices = get_us_quotes_batch(["NVDA", "TSM", "ASML"])
for sym, quote in us_prices.items():
    if quote:
        print(f"{sym}: {quote['change_pct']:+.2f}%")
```

## 集成到 run_alert.py 的建议

### 方案 A：在日报前显示美股背景
```python
# run_alert.py 开头
from us_context import show_us_context

def main_loop():
    show_us_context()  # 显示美股背景
    # ... 继续选股、监控逻辑
```

### 方案 B：在买点过滤中加入美股确认
```python
# strategy_engine.py 或 buy_filter 中
from us_context import us_context_for_buy_filter

def should_buy_tech_stock(code):
    us_verdict = us_context_for_buy_filter()
    if us_verdict is False:
        return False  # 美股走弱，不买
    # ... 继续 A 股本地判断
```

### 方案 C：在监控列表中加入美股警报
在 `config.json` 的 `watchlist` 中添加美股标的：
```json
{
  "watchlist": [
    {
      "code": "NVDA",
      "market": "us",
      "alert_above": 230,
      "alert_below": 200,
      "tags": "芯片参考"
    }
  ]
}
```

## 注意事项

1. **免费用 yfinance** — 无需 API Key，但实时性略有延迟（~15 分钟）
2. **缓存设置** — 默认 60 秒缓存；建议交易时段用更短的 TTL
3. **市场时间** — 美股闭市时数据是前一交易日的
4. **网络要求** — 需要能访问 Yahoo Finance，部分代码（如 SOX）可能不支持
5. **定期更新** — 美股对标映射在 `us_quick.py` 中，如需添加新指数可自行扩展

## 常见问题

**Q: 为什么有些代码（如 SOX）获取失败？**  
A: yfinance 并不支持所有美国指数，可改用 Yahoo Finance 上的等价 ETF（如用 XSD 代替 SOX）

**Q: 如何加入实时推送（美股跌破时通知）？**  
A: 在 `quote_us_stocks.py` 基础上，可参考 `risk_control.py` 的通知逻辑

**Q: 能否将美股行情写入 watchlist 的数据库？**  
A: 可以，改造 `kline_store.py` 支持美股 K 线存储即可

---

**快速开始：**
```bash
python us_quick.py              # 看美股走势
python us_context.py            # 看判断建议
python test_us_stocks.py        # 完整测试
```
