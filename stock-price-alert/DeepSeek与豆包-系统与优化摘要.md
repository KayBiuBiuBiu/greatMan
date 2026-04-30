# 股价监控系统（stock-price-alert）— 设计与性能优化摘要

> 供 **DeepSeek、豆包** 等模型快速了解仓库：**业务做什么、技术怎么搭、近期优化了什么、配置怎么开**。  
> 更细的模块与风控逻辑见同目录 `技术设计说明-DeepSeek审阅.md`；优化对照清单见 `性能优化-实施状态.md`。

---

## 一、系统是干什么的

| 模块 | 作用 |
|------|------|
| 轮询监控 | 读 `config.json` 的 `watchlist`，定时拉现价与日 K，控制台 + macOS 通知（可选邮件）。 |
| 成本与仓位 | `RiskManager`：止盈止损、补仓档位、单票/总仓位上限。 |
| 相对成本下跌 | `drawdown_alert`：如 -3%、-6% 相对**成本**提醒，与技术面独立。 |
| **趋势下滑预警** | `trend_slippage_alert`：**个股技术 + 大盘 + 东财行业板块指数(BK)** 三柱；板块数据有效时 **任意 2 柱走弱** 触发；无有效板块 K 时退化为「个股 + 大盘」两柱同时走弱。 |
| 行业板块 | 用东财 **真实** 行业板块指数 `BKxxxx`（`secid=90.BK*`）拉日 K，与个股共用一套均线/MACD/形态/放量子维度逻辑。 |

**不做**：下单、撮合、Level-2、官方 WebSocket 行情（见下文「未做」）。

---

## 二、核心业务逻辑（给模型对齐语义）

1. **板块不是「黑名单/相对强弱」代理**：趋势三柱里的「板块柱」来自 **BK 指数日 K**；`macro_risk` 里行业关键词黑白名单主要服务 **选股打分**，与板块柱分离。  
2. **BK 解析顺序**：当轮内存 → `sector_index_overrides` → 磁盘 `sector_index_cache.json` 的 `by_code` → 东财 `f127` → 失败则用 watchlist 的 `industry` 字符串去匹配行业全表。  
3. **东财请求**：`sector_em` / K 线多域名回退；行业 `clist` 分页已修正（避免只缓存一页）；`industry_map_ttl_sec` 默认约 **1 小时** 减轻全表重拉。

---

## 三、性能与架构优化（阶段一～三，已实现）

### 3.1 阶段一：缓存与去重

| 手段 | 效果 |
|------|------|
| 日 K **进程内 TTL**（个股 / 板块不同 TTL） | 跨轮询少打东财 `his/kline`。 |
| **同轮** `round_bk_kline` + 锁 | 多只股票同一 BK 只拉一次板块 K。 |
| 上证日 K **单次拉取、双指标共用** | `fetch_index_mood_mult` 与 `fetch_index_5d_return` 共用缓存。 |

### 3.2 阶段二：并发与线程安全

| 手段 | 效果 |
|------|------|
| `ThreadPoolExecutor` + `Semaphore` | 多标的并行拉取，默认 workers≈4、并发≈3，可配置。 |
| `_fetch_watch_item_pack` | 单票拉取逻辑集中，便于并发与测试。 |
| 锁 | `get_stock_name`、板块 K 字典、`print`、**`sector_em` RLock**（保护 `_ROUND_RESOLVE` 与磁盘回写，`f127` 在锁外）。 |

### 3.3 阶段三：本地库 + 类推送线程

| 手段 | 效果 |
|------|------|
| **SQLite** `kline_store.py` + `sync_daily_klines.py` | 盘后把 watchlist 个股 + 解析到的板块 K 写入库；监控在「新鲜度」窗口内 **优先读库** 再考虑网络。 |
| **RealtimeQuoteHub** | 独立线程按间隔 HTTP 刷新现价缓存；主循环可优先读缓存（**仍是轮询**，可替换为真 WebSocket）。 |

---

## 四、配置速查（复制到 `config.json` 时按需改）

```json
"performance": {
  "kline_cache_ttl_sec": 300,
  "sector_kline_cache_ttl_sec": 1800,
  "index_kline_cache_ttl_sec": 60,
  "enable_parallel_fetch": true,
  "fetch_max_workers": 4,
  "fetch_max_concurrency": 3
},
"kline_store": {
  "enabled": false,
  "db_path": "data/daily_klines.db",
  "fresh_hours_after_sync": 36
},
"realtime_hub": {
  "enabled": false,
  "poll_interval_sec": 5
}
```

- **开本地日 K**：`kline_store.enabled=true` → 定期跑 `python3 sync_daily_klines.py` → 重启监控。  
- **关并行**（调试用）：`enable_parallel_fetch=false`。  
- **开行情 Hub**：`realtime_hub.enabled=true`。

---

## 五、关键文件一览

| 文件 | 内容 |
|------|------|
| `run_alert.py` | 主循环、并行拉取、`process_watch_pack`、启动/停止 Hub、合并配置。 |
| `quote_eastmoney.py` | 行情、日 K、TTL 缓存、**可选 SQLite 读 K**、`fetch_kline_rows_for_secid`（同步脚本用）。 |
| `sector_em.py` | BK 解析、行业表、**并发安全 RLock**。 |
| `macro_risk.py` | 上证缓存、行业乘子（选股侧）。 |
| `trend_slippage_risk.py` | 三柱趋势下滑判定。 |
| `kline_store.py` | SQLite 表与读写、`is_db_fresh`。 |
| `sync_daily_klines.py` | 盘后写库脚本。 |
| `realtime_hub.py` | 后台行情缓存线程。 |

---

## 六、风险与边界（便于模型审阅）

- 东财仍可能限流：并发与 TTL 缓解但非零风险。  
- `kline_store` 依赖 **同步脚本** 与 `fresh_hours_after_sync`；过期后自动回退网络。  
- `realtime_hub` 与主循环可能短时间 **重复请求** 现价，属取舍；真 WS 需另接数据源。  
- `sector_em` 与多源现价等 HTTP 的 `verify` 由 `sources.ssl_verify` / `ssl_ca_bundle` 统一控制。  

---

## 七、延伸阅读（仓库内）

1. `技术设计说明-DeepSeek审阅.md` — 配置项、BK 链、三柱公式、与 `macro_score_multiplier` 区别。  
2. `性能优化-实施状态.md` — 阶段一～三勾选表与启用步骤。  

---

## 八、声明

本文档仅描述 **软件行为与工程实现**，不构成投资建议；回测与监控结果不代表未来收益。
