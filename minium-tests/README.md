# 家庭聚会助手 Minium 自动化测试

## 手动配置

1. 确认 `config.json` 中的 `project_path` 指向小程序目录。
2. 确认 `dev_tool_path` 指向微信开发者工具 CLI。
   - 默认：`/Applications/wechatwebdevtools.app/Contents/MacOS/cli`
   - 如果不存在，请改成本机实际路径。
3. 确认 `cloud_env_id` 为目标云环境：`cloud1-d9g01no7m292bc511`。
4. 测试前确保微信开发者工具已登录，且项目可正常打开。

## 安装与运行

```bash
cd minium-tests
chmod +x run_tests.sh
./run_tests.sh
```

Windows:

```bat
run_tests.bat
```

报告输出：

```text
minium-tests/outputs/report.html
minium-tests/outputs/screenshots/
```

## 多人测试策略

当前框架默认开启多实例模式：

```json
"manual_multi_instance": true,
"standard_player_count": 6,
"insufficient_player_count": 5,
"virtual_player_prefix": "测试玩家"
```

完整流程测试会使用房主 + 5 个新实例，总计 6 人；人数不足测试会先使用房主 + 4 个新实例，总计 5 人，再加入第 6 人验证开始按钮变为可用。

Minium 多实例依赖 `self.mini.launch_new_weapp()`。如果本机 Minium/开发者工具版本不支持该 API，会在测试中给出明确错误。

云测试钩子仍保留为可选能力：

1. UI-only：默认模式，测试创建房间并执行可见按钮流程，适合冒烟回归和捕获云函数失败。
2. 云测试钩子：把 `config.json` 中 `use_cloud_test_hooks` 改为 `true`，并在对应云函数中实现以下私有 action：
   - `__testSeedPlayers`
   - `__testAdvanceRound`

这些 action 应只在测试环境使用，建议校验 `_test: true` 或单独的测试密钥。

## 覆盖范围

- 趣味抽签：创建房间、准备、开始、揭晓、下一轮
- 谁是卧底：创建房间、准备、发牌、发言/投票
- 你画我猜：创建房间、准备、开始、绘画、猜测
- 猜歌：创建房间、准备、开始播放、抢答/计分
- 身份推理：创建房间、准备、开始、夜晚/白天/投票
- 真心话大冒险：4 位房间模式、开始、投票、平票分支
- 贴头猜词：创建房间、准备、发词、猜测自己词
- **AI迷雾推理局**：3 人开局（云测注入 2 名虚拟玩家）、读本/公聊/证据/投票关键路径

### AI迷雾推理局多人自测

1. 部署云函数 `mysteryReasonRoomService`（含测试 action）。
2. 微信开发者工具打开本项目并登录云开发。
3. 运行：

```bash
cd minium-tests
minitest -m testcases.test_mystery_reason -c config.json -g
```

或单用例：

```bash
minitest -m testcases.test_mystery_reason -c config.json -g --case test_08_mystery_reason_core_flow
```

测试会自动开启 `use_cloud_test_hooks`（仅本模块），调用：

- `__testSeedPlayers`：注入 `minium_test_*` 虚拟玩家（满 3 人）
- `__testMarkAllReady`：读本阶段全员就绪
- `__testAdvanceRound`：跳过超长倒计时阶段

注入测试玩家后，剧本生成走本地模板兜底（更快、不依赖 AI）。

## 单独运行某个用例

```bash
minitest -m testcases.test_all_games -c config.json -g --case test_11_undercover_insufficient_players
```

也可以直接跑整个 suite：

```bash
./run_tests.sh
```

## 📊 当前进度 (2026-06-01)

### 测试成果
- ✅ **11/17 用例通过** (64.7% ~ 70.6%)
- ✅ **所有 7 个游戏完整流程通过**
- ✅ **4/6 人数不足场景通过**
- ⚠️ **2-3 条用例待修复** (mystery-reason + song-guess 边界)

### 已验证的云函数改造
| 服务 | 改动 | 状态 |
|------|------|------|
| werewolfService | start + 跳过组长校验 | ✅ |
| drawRoomService | startGame | ✅ |
| headbandRoomService | startGame / 修复 | ✅ |
| roomService | tdStart | ✅ |
| drinkRoomService | startRound | ✅ |
| musicRoomService | startGame | ⚠️ 需排查 |
| 其他 5+ 服务 | 测试模式支持 | ✅ |

### 快速诊断

遇到连接错误？参考：
- **连接拒绝 (ConnectionRefused)** → 检查微信开发者工具是否运行，确认 `test_port` 正确
- **wx.cloud.callFunction not exists** → 确保小程序已编译，在开发者工具中点击「编译」
- **超时 (timeout)** → 修改 `config.json` 的 `default_timeout` 为 15-20

详见 **TROUBLESHOOTING.md** 和 **COMPLETION_SUMMARY.md**。

### 下一步

```bash
# 再运行一遍完整测试，预期达到 14-15/17 通过
cd /Users/haha/greatMan/minium-tests
python3 run_tests.py 2>&1 | tee run_$(date +%Y%m%d_%H%M%S).log
```
