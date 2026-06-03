#!/usr/bin/env python3
"""快速测试全球背景集成"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sector_em import format_global_context_line

# 测试几个真实股票
test_codes = [
    ('600711', '盛屯矿业'),
    ('002110', '盛屯矿业'),
    ('688008', '澜起科技'),
    ('300750', '宁德时代'),
]

print("=" * 100)
print("【全球背景集成测试 - 板块行后的全球背景】")
print("=" * 100)

for code, name in test_codes:
    print(f"\n[{code}] {name}")
    print(f"  板块：（假设已显示）")
    line = format_global_context_line(code)
    if line:
        print(f"  {line}")
    else:
        print(f"  （无全球背景信息）")

print("\n" + "=" * 100)
