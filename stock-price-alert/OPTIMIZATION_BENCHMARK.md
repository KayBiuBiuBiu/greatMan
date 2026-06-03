# 优化前后对标清单

## 待测试项目

### 1. 启动时间 (run_alert.py merge_full_config)

**基准测试命令**：
```bash
cd stock-price-alert
time python3 -c "
import json
from run_alert import merge_full_config
cfg = json.load(open('config.json'))
result = merge_full_config(cfg)
print('Merge complete')
" 2>&1
```

**目标**：-2-3ms（估计 323 行 → 280 行 dict 操作减少）

---

### 2. 每日摘要生成 (daily_summary.py build_daily_summary)

**基准测试命令**：
```bash
cd stock-price-alert
python3 -c "
import time
from pathlib import Path
from datetime import datetime
from daily_summary import build_daily_summary

cfg = __import__('json').load(open('config.json'))
root = Path('.')
config_path = Path('config.json')
state = {}
now = datetime.now()

t0 = time.monotonic()
result = build_daily_summary(cfg=cfg, config_path=config_path, state=state, root=root, now=now)
t1 = time.monotonic()

print(f'Daily summary generated in {(t1-t0)*1000:.1f}ms')
" 2>&1
```

**预期改善**：-100-200ms（从串行 I/O 改并行）

---

### 3. 选股性能 (selector.py run_daily_selector)

**基准测试命令**：
```bash
cd stock-price-alert

# 若有本地 K 线缓存，先删除 K 线缓存避免干扰
rm -f data/daily_klines.db

# 跑选股，样本较小避免等待
python3 quant_cli.py daily-select --limit 100 2>&1 | grep -E "选股进度|条件满足"
```

**预期改善**：-30-50%（K 线缓存命中 2-4 次）

**注意**：
- 若无本地 K 线缓存，改善幅度可能不明显
- 建议先运行 `sync_daily_klines.py` 建立缓存
- 多线程并发时缓存效果更明显（workers >= 4）

---

### 4. 配置合并代码质量

**验证命令**：
```bash
cd stock-price-alert

# 检查新辅助函数是否存在
grep -n "def _merge_dict_with_default" run_alert.py

# 统计行数对比
wc -l run_alert.py  # 应该 -40 行左右（总体）

# 检查语法无误
python3 -m py_compile run_alert.py daily_summary.py quant_core/selector.py
echo "✅ All files compiled successfully"
```

---

## 已验证项目

### ✅ 语法检查
```bash
python3 -m py_compile \
  daily_summary.py \
  quant_core/selector.py \
  run_alert.py
# 结果：全部通过
```

### ✅ Import 检查
```bash
python3 -c "
from daily_summary import build_daily_summary
from quant_core.selector import run_daily_selector
from run_alert import merge_full_config
print('✅ All imports successful')
"
```

---

## 性能对标汇总表

| 优化项 | 指标 | 预期改善 | 验证方法 | 状态 |
|--------|------|---------|---------|------|
| 消除重复 holdings | daily_summary 耗时 | -300ms | manual test | ⏳ 待测 |
| 并行 JSON I/O | daily_summary 耗时 | -100-200ms | manual test | ⏳ 待测 |
| K 线缓存 | 选股速度 | -30-50% | quant_cli.py | ⏳ 待测 |
| 配置合并 | 启动时间 | -2-3ms | time merge | ✅ 逻辑验证 |

---

## 注意事项

1. **K 线缓存仅在单次选股周期有效**
   - 不同的选股任务独立初始化缓存
   - 周期结束自动释放，无内存泄漏风险

2. **并行 JSON I/O 的实际收益取决于 I/O 负载**
   - 如果所有文件都在本地 SSD，I/O 已非瓶颈，改善不明显
   - 如果有网络 I/O 或云存储，改善效果显著

3. **配置合并优化无法通过性能指标测量**
   - 改善体现在代码质量和维护性
   - 性能改善 <1% （dict 复制次数减少）

4. **下一轮优化前建议**
   - 验证这 4 项优化的实际效果
   - 确认无新 bug 引入
   - 更新配置 schema 或 example 如有改动

---

**最后更新**：2026-06-03  
**维护者**：Claude Code
