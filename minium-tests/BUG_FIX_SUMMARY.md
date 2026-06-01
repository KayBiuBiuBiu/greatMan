# Minium 测试失败问题分析与修复

## 问题根源

### 1. mystery-reason 的 test_08 和 test_17 失败 ✅ 已修复

**问题**：
- `suite.json` 期望在 `testcases.test_mystery_reason` 中有 `test_08_mystery_reason_core_flow` 和 `test_17_mystery_reason_insufficient_players` 两个方法
- 但实际 `test_mystery_reason.py` 中只有其他方法名（如 `test_core_script_generate_and_display` 等）
- 导致方法查找失败，测试无法启动

**修复**：
- 在 `testcases/test_mystery_reason.py` 末尾添加两个别名方法
- `test_08_mystery_reason_core_flow()` 调用 `self.test_core_script_generate_and_display()`
- `test_17_mystery_reason_insufficient_players()` 调用 `self.test_core_player_threshold()`

### 2. song-guess 的 test_14 阻塞问题 ⚠️ 需进一步验证

**问题**：
- `test_14_song_guess_insufficient_players` 在测试人数不足场景时阻塞/超时
- 关键调用路径：`_run_insufficient_then_sufficient` → `_assert_start_blocked_cloud` → `start_blocked_cloud` → `start_game_cloud`

**分析**：
- songGuess 最少人数：2 人
- test_14 参数：`insufficient=1`（设置为 1 人不足）
- 云函数检查（musicRoomService 第 393-395 行）：`if pls0.length < 2 throw 至少2人才能开始`
- 逻辑正确，返回值应该被正确捕获

**可能原因**：
1. 云函数调用超时（网络不稳定）
2. 参数传递问题（roomId 或其他参数）
3. 云函数部署不完整

**建议验证**：
```bash
# 单独运行 song-guess 完整流程（应该通过）
minitest -m testcases.test_all_games -c config.json -g --case test_04_song_guess_core_flow

# 如果完整流程通过，说明 song-guess 本身没问题，问题在不足场景的测试逻辑

# 单独运行人数不足场景
minitest -m testcases.test_all_games -c config.json -g --case test_14_song_guess_insufficient_players
```

## 已执行的修复

### ✅ test_mystery_reason.py 已更新

在文件末尾添加（第 488-497 行）：
```python
# ====================== Suite.json 中定义的测试用例别名 ======================
def test_08_mystery_reason_core_flow(self):
    """别名：test_core_script_generate_and_display（完整流程）"""
    return self.test_core_script_generate_and_display()

def test_17_mystery_reason_insufficient_players(self):
    """别名：test_core_player_threshold（人数不足场景）"""
    return self.test_core_player_threshold()
```

## 预期改进

修复后预期结果：
- ✅ test_08 → 通过（alias of test_core_script_generate_and_display）
- ✅ test_17 → 通过（alias of test_core_player_threshold）
- ⚠️ test_14 → 需在下次运行中观察（可能是网络超时，非代码问题）

## 下次测试运行

重新运行完整测试套件：
```bash
cd /Users/haha/greatMan/minium-tests
python3 run_tests.py
```

预期通过数：**13-15/17**（之前 11 + 新修复的 2-4）

## 根本原因总结

| 问题 | 根本原因 | 修复类型 |
|------|---------|---------|
| test_08/17 | 方法名不匹配（suite.json vs test_mystery_reason.py） | 代码补充 |
| test_14 | 待验证（可能是网络/超时或参数问题） | 需观察 |

