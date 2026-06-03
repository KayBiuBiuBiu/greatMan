# 🔧 两个有问题的优化 - 深度优化方案

**问题诊断完成** → **优化方案设计**

---

## 问题 1: JSON I/O 并行化无效

### 🔍 根本原因分析

```
当前现象：
  串行执行所有任务：2690ms
  并行执行所有任务：2690ms (无改善)
  
问题诊断：
  ❌ 不是 I/O 本身的问题
  ✅ 问题在于初始化成本
    - 导入模块（第一次 import）
    - ThreadPoolExecutor 创建开销
    - 线程启动成本
    - 数据库连接建立
```

### 💡 优化方案

#### 方案 A：预加载 + 预连接（推荐）
```python
# 在 build_daily_summary 前预加载所有模块
def _preload_modules():
    """提前加载所有需要的模块，避免线程中的首次导入延迟"""
    from account_pnl_daily import build_account_pnl_summary
    from alert_log_store import resolve_alert_db_path
    # ... 其他模块
    return True

def build_daily_summary(...):
    # 第一步：预加载（只做一次）
    _preload_modules()
    
    # 第二步：建立数据库连接（复用）
    conn = sqlite3.connect(...)
    
    # 第三步：并行执行任务（现在没有初始化开销）
    with ThreadPoolExecutor(max_workers=2) as executor:
        ...
```

**收益**：减少线程中的隐藏延迟，并行效果会更好

#### 方案 B：缓存中间结果
```python
# 缓存今天已经生成过的数据
DAILY_SUMMARY_CACHE = {}

def build_daily_summary(...):
    day_iso = now.strftime("%Y-%m-%d")
    
    # 如果今天已经生成过，直接返回缓存
    if day_iso in DAILY_SUMMARY_CACHE:
        return DAILY_SUMMARY_CACHE[day_iso]
    
    # ... 生成过程 ...
    
    # 缓存结果
    DAILY_SUMMARY_CACHE[day_iso] = result
    return result
```

**收益**：避免重复生成

#### 方案 C：优化真正的瓶颈
```python
# 分析：trades_summary 占 870ms（最大）
# 优化它而不是试图并行化

def _collect_trades_summary_optimized(...):
    """优化版本：批量查询而非逐条"""
    # 原始：逐条查询
    # for trade in trades:
    #     query(trade)
    
    # 优化：批量查询
    return conn.execute("""
        SELECT * FROM trades
        WHERE date = ? AND status IN (?, ?, ?)
    """, (day_iso, 'buy', 'sell', 'adjust'))
    # 预编译 SQL、添加索引等
```

**收益**：直击真正瓶颈，效果最大

---

## 问题 2: K线缓存在单独测试中无效

### 🔍 根本原因分析

```
当前问题：
  单独测试 5 只股票：缓存 -4%（无效）
  
真实选股场景：
  3000+ 只股票
  每只需要：评分 + 回测(1年、3年、5年) = 4-5 次 load_df 调用
  ✅ 缓存应该在这个场景中非常有效
  
为什么单独测试无效：
  1. 首次加载本来就要 1.4 秒（API 调用）
  2. 只有 5 只股票，缓存热度低
  3. 字典查询 + 内存访问 < 1ms，收益被加载延迟淹没
```

### 💡 优化方案

#### 方案 A：LRU 缓存替代简单字典（最简单）
```python
from functools import lru_cache
import pandas as pd

# 当前：简单字典
kline_cache = {}

# 优化：LRU 缓存（自动清理冷数据）
@lru_cache(maxsize=300)
def _load_df_cached(code: str, lookback: int = 60) -> pd.DataFrame | None:
    """缓存版本的 load_df"""
    return load_df(code, lookback=lookback, cfg=None)

# 改动 _eval_one_daily_select_stock
def _eval_one_daily_select_stock(...):
    # 改为使用 LRU 缓存版本
    df = _load_df_cached(code, lookback=lookback)
    # 其他代码不变
```

**优点**：
- 自动清理冷数据，防止内存泄漏
- 线程安全
- 效率更高（哈希查询 vs 字典查询）

**缺点**：
- LRU 缓存在线程间共享需要小心

#### 方案 B：预热缓存（激进）
```python
def run_daily_selector(...):
    """选股前预热缓存"""
    
    # 获取样本代码
    sample_codes = test_list[:100]  # 前 100 只
    
    # 预先加载这些数据到缓存
    print("预热缓存...")
    for code in sample_codes:
        load_df(code, lookback=60, cfg=cfg)  # 填充缓存
    
    print("开始选股...")  # 现在缓存已热，之后的访问会很快
    
    # 后续选股逻辑...
```

**优点**：
- 后续访问都能命中缓存
- 缓存命中率 100%

**缺点**：
- 增加启动延迟（但总时间可能还是更短）

#### 方案 C：两级缓存（最优）
```python
# 内存 LRU 缓存（快，但容量有限）
@lru_cache(maxsize=300)
def _load_df_cached(code: str):
    return _load_df_from_disk(code)

# 磁盘缓存（慢，但容量无限）
DISK_CACHE_DIR = Path("data/kline_cache")

def _load_df_from_disk(code: str) -> pd.DataFrame:
    """优先从磁盘缓存读，再从 API 读"""
    cache_file = DISK_CACHE_DIR / f"{code}.parquet"
    
    if cache_file.exists():
        # 磁盘缓存命中（~100ms）
        return pd.read_parquet(cache_file)
    
    # 磁盘缓存未命中，调用 API
    df = load_df(code, ...)
    
    # 存入磁盘缓存供下次使用
    df.to_parquet(cache_file)
    return df
```

**优点**：
- 同一只股票在不同运行中都能命中缓存
- 内存占用受限（LRU 300 只）
- 跨会话复用数据

---

## 🚀 优化优先级

### 立即做（1-2小时）
1. **LRU 缓存替代简单字典** - 方案 A（K线缓存）
2. **预加载模块** - 方案 A（JSON I/O）

### 本周做（可选）
3. **缓存中间结果** - 方案 B（JSON I/O）
4. **优化 trades_summary** - 方案 C（JSON I/O，最有效）
5. **两级缓存架构** - 方案 C（K线缓存，长期）

### 完整对标后决策
- 运行 `--full` 看实际效果
- 如果 K线缓存显示 >20% 改善 → 投入时间优化
- 如果 JSON I/O 仍无明显改善 → 优化真正的瓶颈

---

## 📋 具体代码改动（立即可做）

### 改动 1: K线缓存用 LRU
```python
# quant_core/selector.py

from functools import lru_cache

# 替代原来的简单字典缓存
@lru_cache(maxsize=300)
def _load_df_cached(code: str, lookback: int = 60) -> pd.DataFrame | None:
    """带 LRU 缓存的 K 线加载"""
    return load_df(code, lookback=lookback, cfg=None)

# 修改 _eval_one_daily_select_stock
def _eval_one_daily_select_stock(
    code: str,
    *,
    cfg: dict[str, Any],
    ...
    # kline_cache 参数可以删除
) -> tuple[str, dict[str, Any]]:
    """改为使用 LRU 缓存版本"""
    df = _load_df_cached(code, lookback=lookback)  # 使用 LRU 缓存
    # 其他代码不变
```

**改动：**
- 删除 `_KLINE_CACHE` 全局变量
- 删除 `kline_cache` 参数传递
- 使用 `@lru_cache` 装饰器

### 改动 2: 预加载模块
```python
# daily_summary.py

def _preload_modules():
    """启动时预加载所有模块，避免线程中的首次导入延迟"""
    try:
        from account_pnl_daily import build_account_pnl_summary
        from alert_log_store import resolve_alert_db_path
        return True
    except Exception:
        return False

def build_daily_summary(...):
    # 第一步：预加载模块（只做一次）
    _preload_modules()
    
    # 第二步：后续并行执行
    with ThreadPoolExecutor(max_workers=4) as executor:
        ...
```

---

## 📊 预期效果对比

### 当前状态
```
JSON I/O 并行：2690ms（无改善）
K线缓存：-4%（无效）
```

### 优化后预期

#### K线缓存（LRU）
```
完整选股场景（3000 只，每只 4-5 次调用）：
  无缓存：3000 × 1.4s = 4200s
  有缓存：(3000 × 1.4s) + (12000 × 0.001s) ≈ 4200 + 12 = 4212s
  
⚠️ 单独看没差，但在重复场景中：
  第2次运行同样 3000 只：(3000 × 0.001s) = 3s（vs 4200s）
  ✅ 改善 99%
```

#### JSON I/O（预加载 + 优化瓶颈）
```
原始：2690ms
预加载后：2500ms（省去初始化）
优化 trades_summary：2000ms（从 870ms → 200ms）
总改善：26% (2690 → 2000)
```

---

## 🎯 建议行动方案

### 今天（30分钟）
```bash
# 1. 修改 selector.py 用 LRU 缓存
# 2. 修改 daily_summary.py 预加载模块
# 3. 验证编译通过
git diff
git add ...
git commit -m "perf: 优化 K线缓存和 JSON I/O 初始化"
```

### 本周（可选，但高效）
```bash
# 运行完整对标，观察效果
python3 performance_benchmark.py --full

# 如果 K线缓存显示 >20% 改善：
#   投入时间优化 trades_summary（真正瓶颈）
```

---

## 💡 关键洞察

**为什么要这样优化**：

1. **JSON I/O 并行化的真正瓶颈不在 I/O**
   - 是模块加载和初始化
   - 预加载解决这个问题
   
2. **K线缓存需要在完整场景验证**
   - 单独测试看不出效果
   - 用 LRU 缓存是保险的做法
   
3. **性能优化的黄金法则**
   - 测量 → 找瓶颈 → 优化瓶颈（不是优化看起来快的地方）
   - 预加载 / 缓存常常是最简单有效的

---

**建议**：先做这两个改动（30分钟），然后运行 `--full` 对标看效果，再决定是否需要更深度的优化。

生成时间：2026-06-03 16:50
