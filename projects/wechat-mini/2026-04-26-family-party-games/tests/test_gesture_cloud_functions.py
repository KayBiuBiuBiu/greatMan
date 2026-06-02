"""
你比划我猜 - 云函数单元测试
可以在微信开发者工具的云函数管理面板直接测试
"""

# 测试用例 1: 创建房间
TEST_CREATE = {
    "action": "create",
    "nickName": "玩家A",
    "totalRounds": 5,
    "roundDuration": 60,
    "wordCategory": "all",
    "_test": True
}

# 测试用例 2: 加入房间（需要从创建结果中获取 roomCode）
TEST_JOIN = {
    "action": "join",
    "roomCode": "000001",  # 从创建结果中获取
    "nickName": "玩家B"
}

# 测试用例 3: 开始游戏
TEST_START = {
    "action": "startGame",
    "roomId": "room_id_from_create",  # 从创建结果中获取
    "_test": True
}

# 测试用例 4: 提交答案（正确）
TEST_GUESS_CORRECT = {
    "action": "submitGuess",
    "roomId": "room_id",
    "answer": "苹果"  # 应该与 currentWordText 匹配
}

# 测试用例 5: 提交答案（错误）
TEST_GUESS_WRONG = {
    "action": "submitGuess",
    "roomId": "room_id",
    "answer": "错误答案"
}

# 测试用例 6: 跳过词语
TEST_SKIP = {
    "action": "skipWord",
    "roomId": "room_id"
}

# 测试用例 7: 揭晓答案
TEST_REVEAL = {
    "action": "reveal",
    "roomId": "room_id"
}

# 测试用例 8: 下一轮
TEST_NEXT = {
    "action": "nextRound",
    "roomId": "room_id"
}

# 测试用例 9: 获取视角
TEST_VIEW = {
    "action": "getView",
    "roomId": "room_id"
}

# 测试用例 10: 同步状态
TEST_SYNC = {
    "action": "syncState",
    "roomId": "room_id"
}


# ==================== 测试步骤 ====================
#
# 在微信开发者工具中：
# 1. 云开发 → 云函数 → gestureRoomService
# 2. 点击「测试」按钮
# 3. 依次输入上述 TEST_* 对象并执行
#
# 预期结果顺序：
#
# 第1步：创建房间
#   输入：TEST_CREATE
#   预期：返回 { roomId, roomCode, ok: 1 }
#   ✓ 房间创建成功
#
# 第2步：第二个玩家加入
#   输入：TEST_JOIN
#   修改 roomCode 为第1步返回的值
#   预期：返回 { roomId, playerCount: 2, ok: 1 }
#   ✓ 玩家加入成功
#
# 第3步：开始游戏
#   输入：TEST_START
#   修改 roomId 为第1步返回的值
#   预期：返回 { performerOpenId, ok: 1 }
#   ✓ 游戏开始，指定表演者
#
# 第4步：获取个人视角
#   输入：TEST_VIEW
#   修改 roomId 为第1步返回的值
#   预期：返回 { performerWord, isPerformer, publicPlayers, ... }
#   ✓ 看到表演者词语（如果是表演者）
#
# 第5步：提交正确答案
#   输入：TEST_GUESS_CORRECT
#   修改 roomId、answer 为实际词语
#   预期：返回 { ok: 1, points: 3, newScore }
#   ✓ 答题成功，得分 +3
#
# 第6步：揭晓答案
#   输入：TEST_REVEAL
#   修改 roomId 为实际值
#   预期：返回 { ok: 1 }
#   ✓ 答案已揭晓
#
# 第7步：下一轮
#   输入：TEST_NEXT
#   修改 roomId 为实际值
#   预期：返回 { nextRound: 2, ok: 1 }
#   ✓ 进入下一轮
#
# ==================== 测试结果示例 ====================
#
# ✓ TC-01: 创建房间
#   云函数返回：
#   {
#     "roomId": "63abc123def456",
#     "roomCode": "123456",
#     "myOpenId": "oXXXXXXXXXXX",
#     "ok": 1
#   }
#
# ✓ TC-02: 加入房间
#   云函数返回：
#   {
#     "roomId": "63abc123def456",
#     "roomCode": "123456",
#     "playerCount": 2,
#     "myOpenId": "oYYYYYYYYYYY",
#     "ok": 1
#   }
#
# ✓ TC-03: 开始游戏
#   云函数返回：
#   {
#     "ok": 1,
#     "performerOpenId": "oXXXXXXXXXXX",
#     "currentWord": "苹果"
#   }
#
# ✓ TC-04: 获取视角
#   云函数返回：
#   {
#     "myOpenId": "oXXXXXXXXXXX",
#     "isHost": true,
#     "isPerformer": true,
#     "performerWord": "苹果",
#     "publicPlayers": [
#       { "openId": "oXXXXXXXXXXX", "nickName": "玩家A", "score": 0 },
#       { "openId": "oYYYYYYYYYYY", "nickName": "玩家B", "score": 0 }
#     ]
#   }
#
# ✓ TC-05: 提交答案（正确）
#   云函数返回：
#   {
#     "ok": 1,
#     "points": 3,
#     "order": 1,
#     "newScore": 3
#   }
#
# ✓ TC-06: 提交答案（错误）
#   云函数返回：
#   {
#     "wrong": 1,
#     "ok": 0
#   }
#
# ✓ TC-07: 揭晓答案
#   云函数返回：
#   {
#     "ok": 1
#   }
#
# ✓ TC-08: 下一轮
#   云函数返回：
#   {
#     "ok": 1,
#     "nextRound": 2,
#     "performerOpenId": "oYYYYYYYYYYY"
#   }
#
# ==================== 常见问题排查 ====================
#
# Q: 提示"房间不存在"
# A: 确认 roomId 或 roomCode 正确，房间未过期（4小时TTL）
#
# Q: "仅房主可开始"
# A: 确认当前操作用户是房主，或使用 _test: true 旁路检查
#
# Q: "至少需要2人"
# A: 需要两个不同 openId 的玩家，先 join 再 start
#
# Q: 答题总是错误
# A: 检查 answer 是否与 currentWordText 完全匹配（忽略大小写和空格）
#
# Q: 云函数返回 502 或超时
# A: 检查 gestureRoomService 是否已上传部署，查看云函数日志
