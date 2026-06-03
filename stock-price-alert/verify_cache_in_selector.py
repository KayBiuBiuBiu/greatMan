"""在实际选股中验证缓存效果"""
import time
import json
from pathlib import Path
from quant_core.selector import run_daily_selector

# 加载真实配置
cfg_path = Path("config.json")
with open(cfg_path) as f:
    cfg = json.load(f)

print("=" * 60)
print("🧪 选股中的缓存效果验证 (limit=20)")
print("=" * 60)

print("\n[第1次] 选股运行 - 缓存冷启动")
start = time.time()
try:
    result1 = run_daily_selector(
        cfg=cfg,
        limit=20,
        config_parent=cfg_path.parent
    )
    t1 = time.time() - start
    print(f"  ✓ 完成，耗时: {t1:.1f}s")
    print(f"  找到 {len(result1)} 只符合条件的股票")
except Exception as e:
    print(f"  ✗ 错误: {type(e).__name__}: {str(e)[:100]}")
    t1 = time.time() - start
    print(f"  已耗时: {t1:.1f}s")

print("\n[第2次] 选股运行 - 缓存应该命中")
start = time.time()
try:
    result2 = run_daily_selector(
        cfg=cfg,
        limit=20,
        config_parent=cfg_path.parent
    )
    t2 = time.time() - start
    print(f"  ✓ 完成，耗时: {t2:.1f}s")
    print(f"  找到 {len(result2)} 只符合条件的股票")
except Exception as e:
    print(f"  ✗ 错误: {type(e).__name__}: {str(e)[:100]}")
    t2 = time.time() - start
    print(f"  已耗时: {t2:.1f}s")

if 't1' in locals() and 't2' in locals() and t1 > 0:
    print("\n📈 性能对比:")
    print(f"  第1次 (冷启动): {t1:.1f}s")
    print(f"  第2次 (缓存热): {t2:.1f}s")
    if t1 > 0:
        print(f"  改善率: {100*(1-t2/t1):.1f}%")
    
    if t2 < t1:
        print(f"\n✅ 缓存有效 - 节省 {(t1-t2):.1f}s")
    else:
        print(f"\n⚠️ 缓存效果有限")
