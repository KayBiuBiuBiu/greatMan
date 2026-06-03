# Minium 测试分工 — Coding Plan × Agent

> **Coding Plan** 改小程序代码 + 写/更新测试文档与 Page Object。  
> **Agent（Cursor）** 按本文跑 Minium、修测试脚本、输出 PASS/FAIL 报告。  
> 用户只需说：「按 MINIUM_AGENT_HANDOFF 跑你画我猜」或 `@MINIUM_AGENT_HANDOFF.md`。

---

## 1. 分工

| 谁 | 做什么 | 交付物 |
|----|--------|--------|
| **Coding Plan** | 功能实现、云函数、`data-testid`、测试钩子 | PR + 文档「Minium 验收」小节（suite、命令、通过标准） |
| **Agent** | 开自动化、跑 suite、看 `outputs/` | 测试报告（见 §6 模板）+ 必要时修 `pages/`、`testcases/` |
| **用户** | 首次登录微信开发者工具、部署云函数 | 保持 IDE 打开、需要时 Cmd+B 编译 |

**Agent 不负责**：大功能设计、改游戏业务逻辑（除非测试失败且根因在业务代码，需与用户确认后再改）。

---

## 2. 环境（Agent 每次跑测前检查）

```bash
PROJECT="/Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games"
CLI="/Applications/wechatwebdevtools.app/Contents/MacOS/cli"

# 1) 打开项目 + 启用本地自动化（端口 9420）
"$CLI" open --project "$PROJECT"
"$CLI" auto --project "$PROJECT" --auto-port 9420

# 2) 确认端口
lsof -nP -iTCP:9420 -sTCP:LISTEN
```

| 项 | 要求 |
|----|------|
| 小程序路径 | `config.json` → `project_path`（默认上列 PROJECT） |
| 自动化端口 | `minium-tests/config.json` → `test_port: 9420` |
| 云环境 | `cloud_env_id` 与 `cloudbaserc.json` 一致 |
| 云函数 | 对应 `*RoomService` 已部署（绿色） |
| 编译 | 开发者工具内 Cmd+B，预览无报错 |

---

## 3. 命令速查

工作目录一律：`/Users/haha/greatMan/minium-tests`

```bash
# 全量回归（suite.json，约 17 条）
./run_tests.sh
# 或
minitest -m testcases -c config.json -s suite.json -g

# 单游戏 suite（Coding Plan 新增游戏时复制改 suite_*.json）
minitest -m testcases -c config.json -s suite_draw_guess.json -g

# 单条用例
minitest -m testcases.test_all_games -c config.json -g --case test_03_draw_guess_core_flow
```

### 3.1 已登记的 suite 文件

| 文件 | 范围 |
|------|------|
| `suite.json` | 全游戏核心流程 + 人数不足 + 成员展示 |
| `suite_draw_guess.json` | 你画我猜（Canvas 文档配套） |

### 3.2 项目内独立脚本（非 minium-tests）

| 游戏 | 脚本 | 命令 |
|------|------|------|
| 你比划我猜 | `projects/.../tests/test_gesture_final.py` | `cd projects/.../family-party-games && make minium` |

---

## 4. Coding Plan 交付模板（复制到 PR / 测试文档末尾）

```markdown
## Minium 验收（交给 Agent）

- **游戏**：
- **suite**：minium-tests/suite_xxx.json
- **命令**：`cd minium-tests && minitest -m testcases -c config.json -s suite_xxx.json -g`
- **前置**：9420 自动化已开；云函数 `xxxRoomService` 已部署
- **通过标准**：N/N 无 FAIL/ERROR；报告见 outputs/report.html
- **新增 testid**：（如有）`data-testid="enter-drawing"` 等
- **云测钩子**：（如有）`__testSeedPlayers` / `applyTestSyncSnapshot`
```

---

## 5. Agent 执行清单

1. 读 Coding Plan 文档中的「Minium 验收」小节  
2. 执行 §2 环境检查（IDE + 9420）  
3. 运行指定 `minitest` 命令  
4. 失败时按顺序排查：  
   - 连接拒绝 → IDE / 端口 / `test_port`  
   - `wx.cloud.callFunction未实现` → 正常，框架会 fallback 到 `tcb fn invoke`  
   - Page API 不匹配 → 修 `pages/*_page.py` 或 `testcases/`  
   - 元素找不到 → 补 `data-testid` 或改 Page 选择器（反馈 Coding Plan）  
5. 填写 §6 报告回复用户  

**报告与截图**：`minium-tests/outputs/report.html`、`outputs/<timestamp>/`

---

## 6. 测试报告模板（Agent 回复用户）

```
日期：
游戏：
命令：
环境：微信开发者工具 / test_port 9420

结果：✅ N/N 通过  或  ⚠️ X 失败 Y 错误

明细：
| 用例 | 结果 | 备注 |
|------|------|------|
| test_xx_... | PASS/FAIL | |

失败摘要：（堆栈一行 + 建议：修脚本 / 修页面 / 重部署云函数）

报告：minium-tests/outputs/report.html
```

---

## 7. 已知坑

| 现象 | 处理 |
|------|------|
| `Connection refused` | 开 IDE + `cli auto --auto-port 9420` |
| `applyTestSyncSnapshot not exists` | 页面未加载到对应分包；用 cloud create + `reLaunch` 进房 |
| `DrawPage.create_room(..., difficulty=)` | Page 无此参数，测试里勿传（已修 member_display） |
| `draw-guess-canvas.test.js` | 依赖 `data-testid`，WXML 未加则勿跑；优先 Python suite |
| 你比划我猜 | 用 `make minium` + 项目 `config.json`（端口自动探测 WebSocket） |

---

## 8. 相关文档

| 文档 | 用途 |
|------|------|
| `minium-tests/README.md` | 安装、全量 suite、多人策略 |
| `projects/.../TEST-MANUAL-DRAW-GUESS.md` | 你画我猜 Canvas 手动/自动化场景 |
| `projects/.../MINIUM_LOCAL_TEST.md` | 你比划我猜 Minium |
| `projects/.../LOCAL_TEST_GUIDE.md` | 比划我猜快速命令 |

---

*维护：新增游戏 suite 或改端口时同步更新 §3.1 与 Coding Plan 交付模板。*
