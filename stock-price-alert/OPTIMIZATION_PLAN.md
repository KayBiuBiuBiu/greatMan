# 股票监控系统优化方案 (stock-price-alert)

## 执行摘要

当前系统代码规模达 36K+ 行，其中核心模块存在以下瓶颈：
- **run_alert.py**: 9850 行，包含 3 个超大函数（main 1363 行、process_watch_pack 1010 行、_handle_runtime_command 772 行）
- **quote_tushare.py**: 3557 行，复杂的 API 限流逻辑（3 个独立限流器，忙轮询低效）
- **quant_core/selector.py**: 2116 行，并发选股效率低（批处理未优化）
- **配置系统**: merge_full_config() 323 行，~25 处 dict.update 样板代码重复

本文提出 **8 项优化方案**，预期收益：
- 启动速度 +5-10%
- 全市场选股速度 +20-30%
- 代码可维护性大幅提升，bug 减少 15-20%

---

## 优化方案详表（按优先级）

### ★★★★★ 优先级 1 - 高ROI快速胜利

#### 1. 配置合并系统重构

| 属性 | 值 |
|------|-----|
| **文件** | `run_alert.py` - `merge_full_config()` (L1786-2103, 323 行) |
| **当前问题** | 重复 `dict()` 创建 + `update()` 样板 ~25 次，每次启动都执行；嵌套结构更新需多次深拷贝；类型检查（`isinstance(..., dict)`）重复 |
| **优化方案** | 1. 创建 `ConfigBuilder` 类或专用库 (可在 `quant_core/config.py`)；2. 定义配置 schema 类 (dataclass/TypedDict) 替代重复类型检查；3. 实现 `recursive_update()` 函数替代 25 处的 `dict.update()`；4. 缓存已合并配置哈希，快速判断是否需重新合并 |
| **预期收益** | 启动时间 -5-10%；代码行数 -40%（150 → 90 行）；配置逻辑清晰，易扩展 |
| **实现难度** | 2/5 - 低 |
| **投入时间** | 6-8 小时 |
| **风险** | 低 - 保持 config.json schema 不变即可 |
| **验证方法** | 对比启动耗时；单元测试 `recursive_update()`；集成测试验证所有默认值正确合并 |

**具体步骤**：
```python
# 目标：从这样（当前）
cap = dict(DEFAULT_CAPITAL)
cap.update(cfg.get("capital") or {})
cfg["capital"] = cap
# 转为这样（目标）
cfg["capital"] = recursive_update(DEFAULT_CAPITAL, cfg.get("capital") or {})
```

---

#### 2. Tushare API 限流器优化

| 属性 | 值 |
|------|-----|
| **文件** | `quote_tushare.py` - `_acquire_tushare_daily_slot()` 等三个限流函数 (L147-175, L93-114, L117-144) |
| **当前问题** | 3 个独立限流器，各自固定窗口 + 忙轮询；忙轮询 + `time.sleep(0.05-0.15)` 浪费 CPU；限流器间无协调，并发多策略选股时相互干扰 |
| **优化方案** | 1. 创建单一 `RateLimiter` 类，支持多队列 (daily/adj_factor/sw_daily)；2. 改用滑动窗口 token bucket 算法，减少 sleep 调用；3. 添加预测式等待（计算需等待时长而非轮询）；4. 为并发选股提供 burst 预留（避免 1 个任务突破整体限额） |
| **预期收益** | 并发选股等待时间 -15-25%；CPU 使用率 ↓（忙轮询 → 精确 sleep）；API 限流错误 ↓ |
| **实现难度** | 3/5 - 中等 |
| **投入时间** | 8-10 小时 |
| **风险** | 中 - 需充分压力测试 |
| **验证方法** | 并发限流压力测试；对比原算法的等待时间分布；监控 API 限流错误率变化 |

**伪代码示例**：
```python
class RateLimiter:
    def __init__(self):
        self.queues = {
            'daily': deque(),
            'adj_factor': deque(),
            'sw_daily': deque(),
        }
        self.limits = {
            'daily': 500,      # per minute
            'adj_factor': 180,
            'sw_daily': 50,
        }
    
    def acquire(self, queue_name: str) -> float:
        """返回需等待的秒数，0 表示可立即发送"""
        now = time.monotonic()
        # 清理过期请求
        while self.queues[queue_name] and now - self.queues[queue_name][0] >= 60:
            self.queues[queue_name].popleft()
        
        if len(self.queues[queue_name]) < self.limits[queue_name]:
            self.queues[queue_name].append(now)
            return 0.0
        
        # 预测等待时长
        wait_until = self.queues[queue_name][0] + 60
        return max(0, wait_until - now)
```

---

#### 3. 并发选股性能改进

| 属性 | 值 |
|------|-----|
| **文件** | `quant_core/selector.py` - `run_daily_selector()` (L1686-2005)，核心逻辑 L1942-1951 |
| **当前问题** | 使用 `as_completed()` 但结果仍需排序；每个 worker 的 `sleep_sec` 串行累积（选股周期 × 股票数）；无进度估计、无自适应 worker 数 |
| **优化方案** | 1. 改为批处理：~3000 支股票分成 10-20 批，批内并行、批间序列；2. 各批内用 `ThreadPoolExecutor`，减少限流器争抢；3. 添加自适应 worker 数（基于 API 响应时间）；4. 并行计算多策略评分（而非串行） |
| **预期收益** | 全市场选股时间 -20-30%；API 限流错误 ↓；内存占用 ↓（分批加载） |
| **实现难度** | 3/5 - 中等 |
| **投入时间** | 10-12 小时 |
| **风险** | 中 - 需防止竞态条件 |
| **验证方法** | 端到端性能对比；并发竞态检测；内存占用监控 |

**实现要点**：
- 将 3000+ 股票分成 20 个批次（各 150 左右）
- 各批内最多 6 个 worker 并行处理
- 批间顺序处理，避免限流器被同时击中
- 动态调整 worker 数：响应时间 >1s 时减少，<500ms 时增加

---

### ★★★★☆ 优先级 2 - 代码质量优化

#### 4. 大函数拆分

| 属性 | 值 |
|------|-----|
| **文件** | `run_alert.py` 主要函数 + `quote_tushare.py` 部分函数 |
| **当前问题** | 超大函数难以测试、维护；`process_watch_pack()` 混合行情、策略、风控、通知多职责；`main()` 包含初始化、主循环、命令处理等 7+ 职责 |
| **优化方案** | 拆分 `process_watch_pack()` 为：`format_and_display_watch()` + `evaluate_strategy_signals()` + `apply_risk_controls()` + `trigger_notifications()`；拆分 `main()` 为：`_init_from_args_and_config()` + `_run_main_loop()` + `_run_scan_mode()` + `_run_daily_select_mode()` |
| **预期收益** | 每个函数 <300 行；新增测试覆盖 +20-30%；代码复用率提高 |
| **实现难度** | 3/5 - 中等 |
| **投入时间** | 14-18 小时 |
| **风险** | 低 - 不改变外部接口 |
| **验证方法** | 单元测试各拆分函数；集成测试验证原流程正确 |

**拆分示意**：
```
process_watch_pack (1010 行) 
  ├── _format_watch_display (200 行) - 仅负责显示格式
  ├── _evaluate_strategy (250 行) - 仅负责策略评分
  ├── _apply_risk_controls (250 行) - 仅负责风控
  └── _trigger_notifications (150 行) - 仅负责通知

main (1363 行)
  ├── _init_system (200 行) - 初始化
  ├── _run_main_loop (600 行) - 主循环
  ├── _run_scan_mode (300 行) - 全市场扫描
  └── _run_daily_select_mode (200 行) - 盘前选股
```

---

#### 5. 重复代码消除

| 属性 | 值 |
|------|-----|
| **文件** | `run_alert.py`, `quote_tushare.py` 全量 |
| **当前问题** | 3 个相似日志函数 (`_emit_watch_line`, `_emit_fetch_line`, `_emit_main_line`)；风控规则验证重复（多处 `isinstance + dict.get`）；股票代码规范化逻辑重复 |
| **优化方案** | 1. 统一为 `_emit_line(section, rendered, **kwargs)`；2. 提取风控验证为 `RiskRuleValidator` 类；3. 集中管理代码规范化；4. 补充 `utils.py` 常用函数库 |
| **预期收益** | 代码行数 -3-5%；bug 修复 1 处改 1 处；日志路径统一便于修改 |
| **实现难度** | 2/5 - 低 |
| **投入时间** | 4-6 小时 |
| **风险** | 低 - 純代码重构，无逻辑变化 |
| **验证方法** | grep 搜索确保所有调用点已替换；回归测试 |

---

### ★★★☆☆ 优先级 3 - 技术债

#### 6. API 缓存重用策略

| 属性 | 值 |
|------|-----|
| **文件** | `quote_tushare.py`, `quote_eastmoney.py` |
| **当前问题** | stock_basic 缓存是纯 JSON，每次启动都需解析整个文件；stock_to_sw.json 无过期机制；无跨请求响应缓存 |
| **优化方案** | 1. stock_basic 添加 mtime 检查 + 增量更新；2. stock_to_sw 添加版本号 + 7 天过期检查；3. 实现请求去重缓存（LRU，TTL 60s）；4. 添加缓存预热 option |
| **预期收益** | 启动时间 -5-10%；API 调用 -10-15%；数据新鲜度保障 |
| **实现难度** | 2/5 - 低 |
| **投入时间** | 4-6 小时 |
| **风险** | 低 - 纯添加逻辑，不破坏现有缓存 |
| **验证方法** | 对比启动耗时；缓存命中率统计 |

---

#### 7. 异常处理标准化

| 属性 | 值 |
|------|-----|
| **文件** | 全量（`quote_tushare.py`, `run_alert.py`, `quant_core/`） |
| **当前问题** | API 异常处理分散；重试逻辑有 3 种不同的指数退避实现；无统一的异常恢复策略 |
| **优化方案** | 1. 定义 `StockAlertException` 体系 (`RateLimitError`, `NetworkError`, `DataError`)；2. 实现 `retry_with_exponential_backoff()` 装饰器；3. 添加异常恢复配置；4. 集成监控/告警 |
| **预期收益** | 异常处理一致性提高，bug 减少；新增 API 源无需重复实现重试；问题排查更容易 |
| **实现难度** | 3/5 - 中等 |
| **投入时间** | 10-12 小时 |
| **风险** | 低 - 逐模块集成，低风险 |
| **验证方法** | 单元测试异常类和装饰器；集成测试验证重试行为 |

---

#### 8. 测试覆盖率提升

| 属性 | 值 |
|------|-----|
| **文件** | `tests/` - 新增测试用例 |
| **当前问题** | 关键函数如 `process_watch_pack()` 无单元测试；`merge_full_config()` 无集成测试；并发竞态无测试 |
| **优化方案** | 1. 为拆分后函数添加单元测试（mock API）；2. 添加配置合并集成测试；3. 添加并发竞态检测；4. 性能基准测试 |
| **预期收益** | 覆盖率 40% → 65%+；重构时信心提升 |
| **实现难度** | 3/5 - 中等 |
| **投入时间** | 12-14 小时 |
| **风险** | 低 - 纯测试添加 |
| **验证方法** | coverage report；CI/CD 集成 |

---

## 实施路线图

### Phase 1 - 快速胜利（2-3 周）

**并行推进，分工实施**

1. **配置合并重构**（优先级 #1）- 4-6 天
   - 起始条件：无依赖，立即开始
   - 交付物：`quant_core/config.py` + 相关单元测试
   - 上线策略：feature branch → code review → merge main

2. **重复代码消除**（优先级 #5）- 2-3 天
   - 起始条件：无依赖
   - 交付物：统一日志/验证函数 + 替换所有调用点
   - 上线策略：渐进式替换，分多个 commit

3. **大函数拆分初期**（优先级 #4 的 30%）- 3-4 天
   - 起始条件：与上述两项并行
   - 交付物：`process_watch_pack()` 的函数签名拆分
   - 上线策略：预留给 Phase 3

### Phase 2 - 性能优化（2-3 周）

4. **Tushare 限流器优化**（优先级 #2）- 5-7 天
   - 起始条件：Phase 1 完成
   - 前置：充分的并发压力测试
   - 交付物：`RateLimiter` 类 + 压力测试用例
   - 上线策略：灰度上线（金丝雀），监控 API 限流错误

5. **并发选股性能改进**（优先级 #3）- 6-8 天
   - 起始条件：#2 完成
   - 前置：与限流器优化配合测试
   - 交付物：批处理选股 + 自适应 worker
   - 上线策略：AB 测试，对比性能指标

### Phase 3 - 稳定性（1-2 周）

6. **大函数拆分完成**（优先级 #4 的 70%）- 8-10 天
   - 起始条件：Phase 1-2 完成
   - 交付物：完整的拆分函数 + 集成测试
   - 上线策略：保守上线，监控 error 日志

7. **测试覆盖率提升**（优先级 #8）- 8-10 天
   - 起始条件：#4 完成
   - 交付物：覆盖率 40% → 65%+
   - 上线策略：纯测试，无功能变化

---

## 投入估算

| 优化项 | 难度 | 耗时(小时) | 风险 | 收益 | 优先级 |
|-------|------|---------|------|------|-------|
| 配置合并重构 | 2 | 6-8 | 低 | 高 | 1 |
| Tushare 限流器 | 3 | 8-10 | 中 | 高 | 2 |
| 并发选股改进 | 3 | 10-12 | 中 | 高 | 3 |
| 大函数拆分 | 3 | 14-18 | 低 | 中 | 4 |
| 重复代码消除 | 2 | 4-6 | 低 | 中 | 5 |
| API 缓存重用 | 2 | 4-6 | 低 | 低 | 6 |
| 异常处理标准化 | 3 | 10-12 | 中 | 低 | 7 |
| 测试覆盖提升 | 3 | 12-14 | 低 | 中 | 8 |
| **总计** | | **68-86** | | | |

**保守估计总时间**：6-8 周（含测试、Code Review、上线验证、灾难恢复）

---

## 预期收益量化

| 指标 | 当前 | 目标 | 收益 |
|------|------|------|------|
| 启动时间 | 100% | 90-95% | -5-10% |
| 全市场选股耗时 | 100% | 70-80% | -20-30% |
| 代码行数 | 36K+ | 35K+ | -2-3% |
| 测试覆盖率 | 40% | 65%+ | +25% |
| API 限流错误 | 100% | 60-70% | -30-40% |
| 代码复杂度 | 高 | 中等 | 显著改善 |
| 新 bug 发现周期 | 生产环境 | 测试阶段 | 大幅提前 |

---

## 关键风险及缓解措施

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|--------|
| 限流器改动导致 API 错误增加 | 高 | 中 | 灰度上线、充分压力测试、实时监控 |
| 大函数拆分后性能下降 | 中 | 低 | profiling 对比、微基准测试 |
| 配置合并改动破坏兼容性 | 高 | 低 | 保持 config.json schema、版本升级测试 |
| 并发选股引入竞态条件 | 高 | 中 | ThreadSanitizer、压力测试、mock 时钟 |
| 并发选股内存溢出（分批不足） | 中 | 低 | 动态批大小调整、内存监控 |

---

## Code Review 清单

- [ ] 新函数有单元测试，覆盖主路径 + 边界情况
- [ ] 性能改动有 before/after 性能指标对比
- [ ] 配置改动保持 config.json schema 不变
- [ ] 并发改动通过 ThreadSanitizer 或等价工具检查
- [ ] 异常处理改动有集成测试
- [ ] 文档更新（README、config.example.json、troubleshooting）

---

## 后续维护建议

1. **定期性能基准测试**（周期：1 个月）
   - 监控启动时间、选股耗时、API 调用量
   - 发现性能回归时立即修复

2. **测试覆盖率目标**（65% → 75%+）
   - 新代码必须 >80% 覆盖
   - 年度目标 80%+

3. **API 限流监控**
   - 实时报警：限流错误 >2% 时告警
   - 周报：API 调用分布、限流器效率分析

4. **重构后的文档维护**
   - architecture.md：系统组件间关系
   - 各模块 docstring 保持最新

---

## 附录：预期代码示例

### 配置合并优化前后对比

**现状（323 行，~25 次 update）：**
```python
def merge_full_config(raw: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(raw)
    cfg.setdefault("poll_interval_seconds", DEFAULT_POLL)
    cap = dict(DEFAULT_CAPITAL)
    cap.update(cfg.get("capital") or {})
    cfg["capital"] = cap
    br = dict(DEFAULT_BUY_RULE)
    br.update(cfg.get("buy_rule") or {})
    cfg["buy_rule"] = br
    # ... 重复 20+ 次
```

**目标（~90 行，声明式）：**
```python
def merge_full_config(raw: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(raw)
    for key, default_val in CONFIG_DEFAULTS.items():
        cfg.setdefault(key, default_val)
    for key, default_dict in CONFIG_NESTED.items():
        cfg[key] = recursive_update(default_dict, cfg.get(key) or {})
    return validate_config_schema(cfg)
```

### 限流器优化前后对比

**现状（忙轮询）：**
```python
def _acquire_tushare_daily_slot() -> None:
    if lim <= 0:
        return
    window = 60.0
    while True:
        with _daily_rate_lock:
            now = time.monotonic()
            while _daily_rate_mono and now - _daily_rate_mono[0] >= window:
                _daily_rate_mono.popleft()
            if len(_daily_rate_mono) < lim:
                _daily_rate_mono.append(now)
                return
            wait_s = window - (now - _daily_rate_mono[0]) + 0.02
        time.sleep(max(wait_s, 0.05))  # 忙轮询
```

**目标（精确等待）：**
```python
limiter = RateLimiter()

wait_s = limiter.acquire('daily')
if wait_s > 0:
    time.sleep(wait_s)  # 精确 sleep 一次
# 立即发送请求
```

---

**文档维护人**: Stock Alert Team  
**最后更新**: 2026-06-03  
**版本**: 1.0 Draft
