# 观测日志与数据健康 — 近期方案说明（供 DeepSeek 等第三方提建议）

> **用途**：本文与根目录 `技术设计说明-DeepSeek审阅.md`、`观测与性能说明.md` 配合阅读；侧重 **P2-3 结构化日志**、**P1-6 data_health**、**CLI/子命令可观测性** 的**已实现做法**与**未决取舍**，方便你从工程与产品角度给改进建议（不必复述全文设计）。

---

## 1. 背景与目标

- 主监控路径已有 `_emit_watch_line`、`_emit_fetch_line`、`_emit_main_line`（`print` + 条件 `record_alert_event`）。
- 选股/扫描路径已用 `app_logging.emit_select_tool_line`（先 stdout，JSONL 开启时再写一行）。
- **问题**：`run_alert.py` 里 `hold` / `showhold` / `--daily-select` / `--check-bk` 等子命令与早期 CLI 输出多为裸 `print`，与主循环日志不同步；**选股侧** `quant_core/data_source.py` 多源现价曾与主监控的 `quote_eastmoney` 并行但不计入 `data_health`，全站 outage 判断易偏差。

**近期目标**：在不牺牲控制台可读性的前提下，统一「可进 JSONL 的关键用户输出」，并让尽可能多的 HTTP 进入 `data_health` 计数。

---

## 2. 已实现要点（摘要）

### 2.1 `app_logging`

- `setup_app_logging(cfg, root=...)`：`logging.enabled` 时挂载 `RotatingFileHandler`，`_JsonLineFormatter` 输出单行 JSON；`extra` 中白名单字段（如 `event`、`section`、`code`、`fails`、`attempted` 等）进入顶层。
- `record_alert_event`：仅在已挂载 JSONL 时写入（避免未配置时刷盘）。
- `emit_select_tool_line(msg, event, section)`：始终 `print` stdout；再 `record_alert_event`（与 JSONL 开关一致）。

### 2.2 `utils.py` 与 HTTP 健康

- `safe_get`：随机等待 + 重试 + `record_http_result` + 全局限流钩子（`performance.request_min_interval_sec`）。
- **`requests_get_with_health` / `session_get_with_health`**：无 `safe_get` 的额外随机等待，仅 `requests.get` / `sess.get` + `record_http_result`（成功用 `str(r.url)`），供多源现价、雪球 Session 等与主监控并列的路径复用。
- `quote_eastmoney.py` 与 **`quant_core/data_source.py`**（新浪/腾讯/雪球/百度/网易）已走上述包装，与东财 K 线经 `safe_get` 的路径互补。

### 2.3 `sector_em.py`

- 成功响应用 **`str(r.url)`** 记录，便于区分 clist 分页与多 host。

### 2.4 `run_alert.py` CLI / 子命令

- **`_emit_cli_subcmd_line(msg, event)`** → `emit_select_tool_line(..., section="run_alert_cli")`。
- **`_cli_print_blank()`**：仅空行，不写 JSONL。
- **`_ensure_app_logging_from_config_path`**：在 `--daily-select`、`--check-bk`、`--backtest-code`、`--test-notify`、自动盘前等**早于主流程第二次 `setup_app_logging`** 的路径上尽早 `setup_app_logging`，使子命令输出也能进 JSONL。
- 已迁移：`showhold` 表、`hold`/`unhold`/`sell`、未知命令用法、`--daily-select` 完成统计、`--check-bk` 行、缺 config 提示、`daily-auto` 衔接句、启动横幅、stdin 非 TTY、watch 为空、监控池空转等待等。

**刻意保留原样**：`[DATA_OUTAGE]` 与 **熔断** 仍为 `print` + 带 `fails`/`attempted`/`degraded_hosts` 的 `record_alert_event`（未改用 `emit_select_tool_line`，以免丢结构化字段）。

### 2.5 测试与 outage 逻辑

- `apply_poll_outage_state_mutations` 从主循环抽出，单元测试覆盖连续全失败 streak、`suppress_trend_rounds_after_full_outage`、恢复分支等（`tests/test_outage_trend_suppress.py`）。
- **尚未做**：在完整 `process_watch_pack` 调用链上 mock `evaluate_trend_slippage_alert` 的「集成级」抑制断言（长期可增强）。

---

## 3. 请你（审阅方）重点给建议的方向

以下是我们**希望得到具体建议**的点（可只评其中几条）：

1. **事件命名与 schema**  
   - 当前 `event` 为自由字符串（如 `cli_showhold_row`、`poll_round_done`）。是否需要 **枚举/前缀规范/文档化 schema**（甚至 CI 校验）以避免漂移？利弊与成本如何权衡？

2. **JSONL 体量与隐私**  
   - `showhold` 每行一条 JSON 可能行数较多；控制台与文件是否应 **分级**（例如 `logging.cli_detail: false` 时只记摘要行）？`note`、成本等是否属于敏感字段，是否应默认脱敏或单独开关？

3. **`section` 划分**  
   - 现有 `watch_pack`、`fetch`、`main_loop`、`run_alert_cli`、`stock_scanner`、`quant_cli` 等。是否建议再拆（如 `cli_hold` vs `cli_showhold`）或合并为更少维度以便检索？

4. **DATA_OUTAGE / 熔断与统一封装**  
   - 是否值得扩展 `record_alert_event` 或新增 `_emit_outage_line`，在保留 `fails`/`attempted`/`degraded_hosts` 的同时去掉裸 `print` 重复？有无更清晰的「告警级别 vs 用户可读段落」分层？

5. **双次 `setup_app_logging`**  
   - 自动盘前路径上可能先 `_ensure_app_logging_from_config_path` 再在 `_run_auto_daily_select` 内 `setup_app_logging`，主流程入口又一次 `setup`。是否有 **幂等/单次初始化** 的更干净模式（例如 lazy singleton logger）？

6. **data_health 与选股**  
   - 选股侧现价现已入账；**akshare** 等库内部请求仍无法挂钩。是否有推荐的 **边界**（文档声明即可 vs 局部 monkeypatch）？

7. **长期项**（仅征求意见，不要求实现）  
   - 全局限流进阶（按域名令牌桶、共享 Session）、真 WebSocket 与当前轮询架构的衔接方式。

---

## 4. 关联文件（便于你打开对照）

| 文件 | 说明 |
|------|------|
| `app_logging.py` | JSONL、`emit_select_tool_line`、`record_alert_event` |
| `utils.py` | `safe_get`、`requests_get_with_health`、`session_get_with_health` |
| `data_health.py` | `record_http_result`、退避、摘要 |
| `run_alert.py` | `_emit_cli_subcmd_line`、`_ensure_app_logging_from_config_path`、主循环 |
| `quant_core/data_source.py` | 选股侧多源现价 |
| `观测与性能说明.md` | JSONL 样例、全失败数字例、性能要点 |
| `技术设计说明-DeepSeek审阅.md` | 全系统模块与配置 |

---

## 5. 审阅输出格式（可选）

若方便，可按：**优点 / 风险或债务 / 优先级化建议（P0–P2）/ 若只改一处则改哪里** 四段给出，便于我们排期落地。
