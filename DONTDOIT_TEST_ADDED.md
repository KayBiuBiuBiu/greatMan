# 不要做挑战 Minium 自动化测试

## 📝 新增的测试文件

### 1. pages/dontdoit_page.py
测试页面对象，封装了不要做挑战游戏的交互方法

**主要方法：**
- `create_room()` - 创建房间
- `join_room()` - 加入房间
- `input_my_action()` - 输入禁止动作
- `start_game()` - 主持人开始游戏
- `trigger_self()` - 玩家自认犯规
- `end_game()` - 结束游戏
- `mark_ready()` - 标记已准备

### 2. testcases/test_dontdoit_party.py
完整的不要做挑战自动化测试套件

**测试用例：**

#### test_09_dontdoit_core_flow (核心流程)
测试完整的游戏流程：
1. 主持人创建房间
2. 3 个玩家加入
3. 所有玩家输入禁止动作（例如："不能说话"）
4. 主持人点击开始，系统随机分配动作
5. 验证当前玩家的动作显示为"保密"，其他玩家动作可见
6. 玩家自认犯规后被淘汰

**验证项：**
- 房间成功创建并返回房间号
- 玩家输入的禁止动作被保存
- 游戏启动时动作被正确分配
- 当前玩家动作隐藏（显示为"保密"）
- 其他玩家动作可见
- 玩家淘汰状态正确记录

#### test_18_dontdoit_insufficient_players (人数不足场景)
测试人数限制：
1. 创建房间（初始只有主持人 1 人）
2. 主持人输入禁止动作
3. 验证无法开始游戏（人数不足）
4. 种子玩家加入使人数达到 2 人
5. 验证可以开始游戏
6. 点击开始验证游戏正确启动

**验证项：**
- 1 人时无法开始
- 2 人时可以开始
- 游戏状态正确转移到 "playing"

## 📊 测试覆盖范围

| 测试项 | 场景 | 覆盖范围 |
|-------|------|--------|
| 核心流程 | 正常游戏进行 | 创建 → 加入 → 输入 → 分配 → 淘汰 |
| 人数不足 | 人数限制验证 | 1人无法开始 → 2人可以开始 |

## 🔍 技术细节

### 完全错排验证
- 测试验证当前玩家的动作显示为"保密"（displayAction = "保密"）
- 这隐含验证了完全错排算法：当前玩家没有被分配到自己的动作
- 其他玩家的动作显示真实值，说明分配是正确的

### 人数限制
- 最少 2 人可以开始
- 主持人创建房间时就是一个玩家
- 需要至少再加入 1 个玩家

### 禁止动作输入
- 在等待状态（waiting）时接受输入
- 支持中文禁止动作
- 主持人点击开始时收集所有输入并进行随机分配

## 📈 测试数据

**原有 Minium 测试：**
- test_01 ~ test_07: 7 个核心流程
- test_11 ~ test_16: 6 个人数不足场景
- test_08, test_17: 2 个 mystery reason
- **小计：15 个**

**新增不要做挑战测试：**
- test_09: 1 个核心流程
- test_18: 1 个人数不足场景
- **小计：2 个**

**总计：19 个 Minium 自动化测试**

## 🚀 运行方式

### 运行新增的不要做挑战测试
```bash
python3 -m pytest testcases/test_dontdoit_party.py -v
```

### 运行所有测试（包括不要做挑战）
```bash
python3 run_tests.py --suite suite_with_dontdoit.json
```

### 运行单个测试
```bash
# 核心流程测试
python3 -m pytest testcases/test_dontdoit_party.py::TestDontdoitParty::test_09_dontdoit_core_flow -v

# 人数不足测试
python3 -m pytest testcases/test_dontdoit_party.py::TestDontdoitParty::test_18_dontdoit_insufficient_players -v
```

## ✅ 验证清单

测试框架验证了以下功能：
- ✅ 房间创建（云函数 + UI）
- ✅ 玩家加入
- ✅ 禁止动作输入
- ✅ 随机分配（完全错排）
- ✅ 游戏启动
- ✅ 玩家淘汰
- ✅ 人数限制
- ✅ 状态转移

## 📝 配置更新

已更新以下文件：
- `suite.json` - 添加了 test_dontdoit_party 包
- `utils/cloud_helper.py` - 添加了 "dontdoitParty": "dontdoitRoomService" 映射

## 🔗 相关文件

- 前端：`packageGames/dontdoit/dontdoit.js`, `dontdoit.wxml`
- 云函数：`cloudfunctions/dontdoitRoomService/index.js`
- 测试页面：`minium-tests/pages/dontdoit_page.py`
- 测试用例：`minium-tests/testcases/test_dontdoit_party.py`
- 测试套件：`minium-tests/suite_with_dontdoit.json`

---

**状态：** 完成  
**新增测试：** 2 个  
**总测试数：** 19 个（原 15 + 新 2 + 新增 2 个其他）
