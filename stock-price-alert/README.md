# stock-price-alert｜个人量化监控（多策略 + 选股 + 风控 + 回测）

## 开箱步骤

```bash
cd stock-price-alert
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

1. **股票池**：同目录已有 **`stock_pool.json`**（约 84 只示例，可自行增删）。  
2. **选股写入监控列表**（会覆盖 `config.json` 里的 `watchlist`）：

```bash
python run_alert.py --scan
```

3. **启动监控**（默认 **仅在沪深交易时段请求行情**，休市只休眠不爬接口）：

```bash
python run_alert.py
```

需要 **休市也轮询** 时：

```bash
python run_alert.py --poll-when-closed
```

---

## 能力一览

| 模块 | 说明 |
|------|------|
| **选股** | `stock_scanner.py`：`scan_rule` 价位区间 + 均线多头 + 箱体偏下，结果写入 `watchlist` |
| **行情** | `quote_eastmoney.py`：东方财富 `stock/get` + `kline/get`，`secid` 使用 **1.xxx / 0.xxx** |
| **风控** | `risk_control.py`：`capital` / `buy_rule` / `risk_rule`，补仓摊薄、止盈止损、仓位上限 |
| **策略** | `strategy_engine.py`：均线 + 箱体提示（含 emoji，仅供参考） |
| **量化内核** | `quant_core/`：数据源层、策略层、选股层、回测层、风控层 |
| **日志** | `trade_log.json`（策略通知触发时追加） |
| **区间价** | `watchlist` 中 `alert_below` / `alert_above` 仍为可选提醒 |

配置里 **`eastmoney_ut": "ea"`** 会在代码中自动映射为站内常用长参数，减少接口异常。

---

## 常用命令

```bash
python run_alert.py --scan              # 选股 -> 写 watchlist
python run_alert.py --once --no-notify    # 跑一轮仅打印
python run_alert.py --test-notify        # 测通知与音效
python run_alert.py --poll-when-closed    # 非交易时段也请求行情
python run_alert.py --daily-select        # 盘前多策略选股，输出 daily_picks.json
python run_alert.py --backtest-code 600711  # 跑 1/3/5 年回测，输出 backtest_report.json
python quant_cli.py daily-select          # 独立量化 CLI：选股
python quant_cli.py backtest --code 600711  # 独立量化 CLI：回测
```

环境变量 **`NO_COLOR=1`** 关闭终端着色。

---

## 配置文件要点

- **`run_only_in_trading_hours`**（默认 `true`）：休市不发起 HTTP，省流量与风控压力。  
- **`scan_pool_max`**：选股时最多遍历股票池前 N 只（默认 80）。  
- **`scan_rule.min_amount` / `max_turnover`**：当前选股脚本以 **价格 + K 线策略** 为主；成交额与换手预留，后续可接字段扩展。  
- **`watchlist`**：`cost_price`、`hold_shares` 填好后启用盈亏、补仓测算、止盈止损。

---

## 文件清单（核心）

| 文件 | 作用 |
|------|------|
| `run_alert.py` | 主程序 |
| `stock_scanner.py` | 选股 |
| `stock_pool.json` | 股票池 |
| `quote_eastmoney.py` | 行情与 K 线 |
| `risk_control.py` | 风控与补仓数学 |
| `strategy_engine.py` | 策略文案 |
| `trade_log.py` | 信号记录 |
| `notify_macos.py` | macOS 通知 |
| `config.json` / `config.example.json` | 配置 |

本工具 **不构成投资建议**，投资有风险。
