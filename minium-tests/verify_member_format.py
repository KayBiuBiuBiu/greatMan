#!/usr/bin/env python3
"""
纯代码静态验证：检查所有游戏文件中的成员显示格式是否已改为"当前X人"
不需要 Minium，只做 grep 和文本检查。
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent / "projects" / "wechat-mini" / "2026-04-26-family-party-games"

# 预期的格式（带"当前"，不带"/"）
EXPECTED_FORMAT_PATTERN = r'当前\s*[\'"]?\+?\s*.*\+?\s*[\'"]?\s*人'
FORBIDDEN_PATTERN = r'[\'"]\s*\+?\s*\d+\s*[\'"]?\s*/\s*[\'"]?\s*\d+\s*[\'"]?\s*人'

def check_file(filepath, patterns_to_find, patterns_to_avoid):
    """检查文件是否包含期望的格式"""
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        return None, f"无法读取: {e}"

    issues = []

    # 检查是否包含不允许的格式（"X/Y 人"）
    for pattern in patterns_to_avoid:
        matches = re.finditer(pattern, content)
        for match in matches:
            line_num = content[:match.start()].count('\n') + 1
            issues.append(f"  ✗ 第 {line_num} 行: 仍然包含 '{match.group()}' (应改为'当前X人')")

    # 检查是否包含期望的格式
    found_expected = False
    for pattern in patterns_to_find:
        if re.search(pattern, content):
            found_expected = True
            break

    return found_expected, issues

def verify_roomui_js():
    """检查 roomUi.js"""
    print("\n📄 检查 packageGames/utils/roomUi.js")
    filepath = PROJECT_ROOT / "packageGames/utils/roomUi.js"

    # 查找 memberCountLine 函数
    content = filepath.read_text(encoding='utf-8')

    # 提取 memberCountLine 函数
    match = re.search(r'function memberCountLine\([^)]*\)\s*\{[^}]*\}', content, re.DOTALL)
    if not match:
        print("  ✗ 无法找到 memberCountLine 函数")
        return False

    func_code = match.group()
    print(f"  函数代码:\n{func_code[:200]}...")

    # 检查不应该包含 "need"
    if '(need | 0) > 0' in func_code or 'if (need' in func_code:
        print("  ✗ 仍然包含 'need' 相关逻辑 (应已移除)")
        return False

    # 检查应该包含"当前"和"人"
    if '当前' in func_code and '人' in func_code:
        print("  ✓ 格式正确: '当前...人' (已移除 X/Y 逻辑)")
        return True
    else:
        print("  ✗ 格式不正确")
        return False

def verify_dontdoit():
    """检查 dontdoit.js 和 wxml"""
    print("\n📄 检查 packageGames/dontdoit/dontdoit.js")
    filepath = PROJECT_ROOT / "packageGames/dontdoit/dontdoit.js"
    content = filepath.read_text(encoding='utf-8')

    all_ok = True

    # 检查 memberCountLine 赋值
    if "'存活 ' + alive + ' / ' + n + ' 人'" in content:
        print("  ✗ 仍然包含旧格式: '存活 X / Y 人'")
        all_ok = False
    elif "'当前 ' + alive + ' 人'" in content:
        print("  ✓ memberCountLine 格式正确: '当前 alive 人'")
    else:
        print("  ⚠ 无法验证 memberCountLine 格式")

    # 检查 statusHint
    if "'🎮 进行中：诱导别人犯规，别做自己的禁止动作（当前 ' + alive + ' 人存活）'" in content:
        print("  ✓ statusHint 格式正确: '当前...人存活'")
    elif "'🎮 进行中：诱导别人犯规，别做自己的禁止动作（存活 ' + alive + ' 人）'" in content:
        print("  ✗ statusHint 仍然是旧格式")
        all_ok = False
    else:
        print("  ⚠ 无法验证 statusHint 格式")

    print("\n📄 检查 packageGames/dontdoit/dontdoit.wxml")
    filepath = PROJECT_ROOT / "packageGames/dontdoit/dontdoit.wxml"
    content = filepath.read_text(encoding='utf-8')

    # 检查 wxml 中的显示
    if '当前 {{aliveCount}} 人' in content:
        print("  ✓ wxml 格式正确: '当前 {{aliveCount}} 人'")
    elif '存活 {{aliveCount}} 人' in content:
        print("  ✗ wxml 仍然是旧格式: '存活 {{aliveCount}} 人'")
        all_ok = False
    else:
        print("  ⚠ 无法在 wxml 中找到成员显示代码")

    return all_ok

def verify_mystery_reason():
    """检查 mystery-reason.js"""
    print("\n📄 检查 packageGames/mystery-reason/mystery-reason.js")
    filepath = PROJECT_ROOT / "packageGames/mystery-reason/mystery-reason.js"
    content = filepath.read_text(encoding='utf-8')

    # 查找 memberCountLine 赋值
    if "memberCountLine: '当前 ' + n + ' 人'" in content:
        print("  ✓ memberCountLine 格式正确: '当前 n 人'")
        return True
    elif 'memberCountLine: n + \'/\' + Math.max(n, 3)' in content:
        print("  ✗ memberCountLine 仍然是旧格式: X/Y")
        return False
    else:
        print("  ⚠ 无法验证 memberCountLine 格式")
        return False

def main():
    print("=" * 60)
    print("🔍 静态验证：成员显示格式统一为'当前X人'")
    print("=" * 60)

    results = []

    try:
        results.append(("roomUi.js", verify_roomui_js()))
        results.append(("dontdoit", verify_dontdoit()))
        results.append(("mystery-reason.js", verify_mystery_reason()))
    except Exception as e:
        print(f"\n✗ 验证过程出错: {e}")
        return 1

    print("\n" + "=" * 60)
    print("📊 验证结果汇总")
    print("=" * 60)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL" if result is False else "⚠ SKIP"
        print(f"{status} — {name}")

    all_passed = all(r for _, r in results if r is not None)

    if all_passed:
        print("\n✅ 所有检查通过！可以上传。")
        return 0
    else:
        print("\n❌ 部分检查失败，请修改后重试。")
        return 1

if __name__ == "__main__":
    sys.exit(main())
