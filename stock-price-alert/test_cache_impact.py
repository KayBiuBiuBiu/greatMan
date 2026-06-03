"""验证 LRU 缓存的实际影响"""
import time
import sys
from pathlib import Path

# 获取当前缓存统计
from quant_core.selector import _load_df_cached

# 清空缓存，测试首次运行
print("=" * 60)
print("🔍 LRU 缓存验证测试")
print("=" * 60)

# 测试代码列表
test_codes = ["600711", "600663", "600105", "002185", "001234"]

print("\n[第1轮] 首次加载（冷启动）")
start = time.time()
for code in test_codes:
    df = _load_df_cached(code)
    if df is not None:
        print(f"  ✓ {code}: {len(df)} bars")
t1 = time.time() - start
print(f"  总耗时: {t1*1000:.1f}ms")

# 清空缓存
_load_df_cached.cache_clear()
print(f"  ✓ 缓存已清空")

print("\n[第2轮] 重复加载（缓存应该命中）")
start = time.time()
for code in test_codes:
    df = _load_df_cached(code)
    if df is not None:
        print(f"  ✓ {code}: {len(df)} bars")
t2 = time.time() - start
print(f"  总耗时: {t2*1000:.1f}ms")

print("\n[第3轮] 再次重复（缓存继续命中）")
start = time.time()
for code in test_codes:
    df = _load_df_cached(code)
    if df is not None:
        print(f"  ✓ {code}: {len(df)} bars")
t3 = time.time() - start
print(f"  总耗时: {t3*1000:.1f}ms")

# 显示缓存信息
cache_info = _load_df_cached.cache_info()
print("\n📊 缓存统计:")
print(f"  命中: {cache_info.hits}")
print(f"  未命中: {cache_info.misses}")
print(f"  命中率: {100*cache_info.hits/(cache_info.hits+cache_info.misses):.1f}%")
print(f"  当前大小: {cache_info.currsize}")

print("\n📈 性能对比:")
print(f"  第1轮 (首次加载): {t1*1000:.1f}ms")
print(f"  第2轮 (缓存命中): {t2*1000:.1f}ms")
print(f"  第3轮 (缓存继续): {t3*1000:.1f}ms")
print(f"  改善率 (1→2): {100*(1-t2/t1):.1f}%")
print(f"  改善率 (1→3): {100*(1-t3/t1):.1f}%")

print("\n✅ 缓存工作正常" if t2 < t1 else "\n⚠️ 缓存效果有限")
