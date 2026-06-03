# stock-price-alert｜个人量化监控（多策略 + 选股 + 风控 + 回测）

> **AI / Coding Plan 速览**：[docs/CODING_PLAN.md](./docs/CODING_PLAN.md)（架构、真相来源、模块地图、常见坑）。  
> **日常运维命令**：[周常时间安排与命令.md](./周常时间安排与命令.md)

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
python run_alert.py --check-bk           # 自检 watchlist 的趋势 BK 映射
python run_alert.py --poll-when-closed    # 非交易时段也请求行情
python run_alert.py --daily-select        # 盘前多策略选股，输出 daily_picks.json
python run_alert.py --backtest-code 600711  # 跑 1/3/5 年回测，输出 backtest_report.json
python ml_train.py --days 180 --model-out data/ml_bearish_nb.json  # 训练 bearish 概率模型
python auto_tune_accuracy.py --dry-run --days 7  # 回测驱动自动调参（预览）
python quant_cli.py daily-select          # 独立量化 CLI：选股
python quant_cli.py backtest --code 600711  # 独立量化 CLI：回测
```

环境变量 **`NO_COLOR=1`** 关闭终端着色。

### 自动化测试（P2-1）

```bash
pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest tests/
```

覆盖：`sector_em` BK 覆盖/磁盘缓存、`trend_slippage_risk` 两柱/三柱触发（配合 monkeypatch 技术计数）、同轮 BK `fetch` 只调用一次、`responses` 模拟 `f127` 单接口。  
使用 **`--once`** 或 **stdin 非 TTY**（如管道/部分 CI）时，不启动后台 `input()` 线程，避免进程退出时与 daemon 线程争抢 stdin 锁。

---

## 回测与实盘

回测（`--backtest-code`）与盘中监控在 **数据时点、滑点/手续费、板块与现价来源** 上均有差异，请勿将回测结果直接当作实盘收益承诺。详见 **[回测与实盘差异说明.md](./回测与实盘差异说明.md)**。

---

## 配置文件要点

- **`run_only_in_trading_hours`**（默认 `true`）：休市不发起 HTTP，省流量与风控压力。  
- **`scan_pool_max`**：选股时最多遍历股票池前 N 只（默认 80）。  
- **`scan_rule.min_amount` / `max_turnover`**：当前选股脚本以 **价格 + K 线策略** 为主；成交额与换手预留，后续可接字段扩展。  
- **`watchlist`**：`cost_price`、`hold_shares` 填好后启用盈亏、补仓测算、止盈止损。
- **`sources.ssl_verify`**：为 `true` 时经 `safe_get`、板块解析、新浪/腾讯等备用现价源的 `requests` 将按布尔校验 TLS；默认 `false` 以兼容部分证书链问题。  
- **`sources.ssl_ca_bundle`**：可选，指向 PEM 文件路径；设置且文件存在时，上述请求使用该 CA 包（内网根证书场景）。  
- **`drawdown_alert.warn_3_ratio`**：可选第三档相对成本回撤预警（如 `-0.1` 表示约 -10%）；不设则不启用该档。  
- **`data_health`（P1-6 首块）**：`enabled: true` 时按 HTTP 主机累计连续失败，`safe_get` / `sector_em._em_get_json` 自动记录；失败达阈值写 **WARNING** 日志；请求前追加 **指数退避** 睡眠。`[DATA_OUTAGE]` 行会附带当前未恢复的主机计数（若已积累）。**合并后默认开启**（可在 `config.json` 中设 `enabled: false` 关闭）。  
- **「全失败」判定（与 `[DATA_OUTAGE]` 一致）**：一轮内对每个 **参与本轮拉取** 的标的计数：`kind=fail` 记失败、`kind=ok` 记尝试成功；`kind=invalid` 不计入。当 **`attempted > 0` 且 `fails >= attempted`** 时，即本轮 **全部拉取失败**（无任一标的拿到可展示行情包），打印 `[DATA_OUTAGE]`，并进入 `data_health` 的连续轮次、可选升级通知/邮件等逻辑（见 `技术设计说明-DeepSeek审阅.md` 4.8）。  
- **`suppress_trend_rounds_after_full_outage`**（`data_health`，默认 `0` 表示关闭）：为 **正整数** 时，在发生上述 **全失败** 的轮次结束时，把状态里的趋势抑制计数 **设为该值**；之后每一轮若在 **非全失败** 下跑完主循环，在 **该轮处理与落盘末尾** 将计数 **减 1**（全失败轮不减）。在抑制计数 **>0** 的轮次内，**不评估、不通知** 趋势下滑预警（其它风控/区间提醒等仍按各自条件执行）。典型用途：数据恢复后的若干轮内暂缓趋势类信号，减少刚恢复时的误报。  
- **`notifications.aggregate_interval_alerts` / `aggregate_max_items`**：区间价提醒合并为每轮一条摘要。**合并后默认开启**。  
- **`notifications.aggregate_trend_alerts` / `aggregate_trend_max_items`**：趋势下滑预警合并为每轮一条摘要（与区间摘要独立）。**合并后默认开启**。  
- **`kline_store`**：本地 SQLite 日 K 优先（库存在且新鲜时减少东财 his 请求）。**合并后默认 `enabled: true`**；无库或过期时自动回退网络，可显式关闭。  
- **`realtime_hub`**：后台线程轮询现价缓存，主循环优先读 Hub。**合并后默认 `enabled: true`**（多一路 HTTP，流量略增）；`ws_enabled` 仍为路线图占位（未接真 WebSocket）。  
- **`logging`（P2-3）**：`enabled: true` 时写 **JSON 行** 到 `logs/run_alert.jsonl`（Rotating）；除 `data_outage`、`fetch_fuse`、`quote_fail`、Ctrl+C 外，监控主循环会写入 **`poll_round_start` / `poll_round_done`（含 `duration_ms`）**、**`watch_*`**（如 `watch_quote`、`watch_trend_slip`）、**`fetch`**（如 `quote_fail`）等，字段含 **`event`、`code`、`rk`、`section`** 等；控制台仍 **保留彩色 `print`**，与 JSONL 并行。**合并后默认开启**。样例、全失败数字例与性能建议见 **[观测与性能说明.md](./观测与性能说明.md)**。
- **`trend_slippage_alert.atr_tiers`（P1-2）**：`enabled: true` 时按近 N 日 **ATR%**（默认 **Wilder** 平滑；`method: simple_ma` / `sma` / `simple` 为原「最近 N 根 TR 简单均值」）分档，覆盖该档的 `stock_min_weak_dims` / `sector_min_weak_dims` / `min_pillars_weak`（见 `config.example.json`）。**合并后默认开启**。
- **配置校验（P2-2）**：`merge_full_config` 之后用 **`config_schema.json`** + `jsonschema` 校验合并结果；类型错误（如把数字写成字符串）会在启动时失败并打印 **路径 + 原因**。根对象对**未知顶层键**不校验类型（便于扩展）；各已知节内**已列出**的子键会做类型约束，未列子键仍允许。`watchlist` 条目：`code` 须 6 位数字，`market` 为 `sh|sz|bj`（大小写均可），`hold_shares` 可为 null 且非负，`cost_price` 可为 null。Schema 顶部 **`$comment`** 要求与 `merge_full_config` 输出保持同步。`quant_cli` 走同一 merge，默认值与监控入口一致。
- **`legal.disclaimer_suffix`**（可选）：覆盖通知/邮件末尾默认免责声明全文。

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
| `config_schema.json` / `config_validate.py` | 合并后配置的 JSON Schema 校验 |
| `data_health.py` | 按主机 HTTP 失败计数与退避（可选） |
| `app_logging.py` | 可选 JSONL 轮转日志 |
| `tests/`、`requirements-dev.txt` | pytest 集成测试（P2-1） |
| `docs/CODING_PLAN.md` | AI/Coding Plan 一页式架构与改代码指南 |
| `周常时间安排与命令.md` | 日常运维与券商交割单命令 |

本工具 **不构成投资建议**，投资有风险。
