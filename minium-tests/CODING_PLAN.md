# 给 Coding Plan — 与 Agent 配合做 Minium

> **你改代码，Agent 跑测。** 用户不会自己跑 `minitest`；你改完按下面 checklist 交付，用户转一句「可以测了」给 Agent 即可。

---

## 30 秒看懂

| 角色 | 做什么 |
|------|--------|
| **你（Coding Plan）** | 功能 / 云函数 / WXML·JS；必要时改 `minium-tests/pages/`、`testcases/`、`suite_*.json` |
| **Agent** | 开微信自动化 → 跑 `minitest` → 修 flaky 脚本 → 给用户 PASS/FAIL 报告 |
| **用户** | 保持微信开发者工具打开 + Cmd+B 编译 |

**Agent 执行手册**（细节、命令、报告模板）：[`MINIUM_AGENT_HANDOFF.md`](./MINIUM_AGENT_HANDOFF.md)

---

## 你画我猜 Minium 闭环（2026-06-03）✅ 已通过

> **状态：Agent 已验收 3/3 PASS。** 下文记录 Coding Plan 初修 + Agent 补修，供后续同类问题对照。

### 验收结果（最终）

```bash
cd /Users/haha/greatMan/minium-tests
minitest -m testcases -c config.json -s suite_draw_guess.json -g
```

| 用例 | 第一次（Coding Plan 后） | 最终 |
|------|-------------------------|------|
| `test_03_draw_guess_core_flow` | ✅ | ✅ |
| `test_13_draw_guess_insufficient_players` | ✅ | ✅ |
| `test_03_draw_guess_member_display` | ❌ | ✅ |

- **报告：** `minium-tests/outputs/report.html`
- **memberCountLine 示例：** `当前 3 人（至少 2 人可开始）`
- **PR 交付文档：** 仓库根目录 [`DRAW_GUESS_PR_DELIVERY.md`](../DRAW_GUESS_PR_DELIVERY.md)

### 第一轮：Coding Plan 已做（必要但不充分）

| 文件 | 改动 |
|------|------|
| `draw-guess.js` `_patchViewFromSync` | 优先 `v.publicPlayers`，再 `_patchRoomUi` → `patchLobbyUi` |
| `test_member_display_format.py` | seed 后加 `page.refresh_lobby(cloud=..., room_id=...)` |

**仍 FAIL 的原因（Agent 跑测发现）：**

1. **`DRAW_GUESS_ENABLED = false`**（`data/feature-flags.js`）  
   Minium `reLaunch` 带 `roomId` 进房后，`onLoad` 约 400ms 跳回 `pages/index/index` → 当前页不是 draw-guess → 日志 `page.applyTestSyncSnapshot not exists` / `afterHasRoomId not exists`。

2. **`applyTestSyncSnapshot` 在 Minium 下仍可能调不通**  
   即使留在 draw-guess 页，IDE 分包未编译或页面栈未就绪时，`call_method` 会失败；需测试侧 `setData` fallback。

### 第二轮：Agent 补修（合并进主线）

#### C. 小程序 — `draw-guess.js` `onLoad` 深链豁免

带 `roomId` 的深链 / Minium 进房时，**不因首页开关跳走**（首页仍可按开关置灰）：

```javascript
const roomIdFromQuery = (q && q.roomId) ? String(q.roomId) : ''
if (!isDrawGuessEnabled() && !roomIdFromQuery) {
  wx.showToast({ title: '你画我猜暂未开放', icon: 'none' })
  setTimeout(function () { wx.reLaunch({ url: '/pages/index/index' }) }, 400)
  return
}
```

#### D. 测试基建 — `minium-tests/utils/cloud_helper.py`

`push_view_to_page(drawGuess)` 在 `applyTestSyncSnapshot` 失败时，用 **`setData` fallback** 注入 `memberCountLine`（格式与 `patchLobbyUi` 一致）：

- `_lobby_member_count_line(n)` → `当前 {n} 人（至少 2 人可开始）`
- `_apply_draw_view_fallback(page_obj, snap, room_id)`

**Coding Plan 请确认已合并上述 C、D**（若 PR 只含 A、B，需补进同一 PR 或 follow-up）。

### Agent 终验回执（2026-06-03，A–D 全部合并后）

> **给 Coding Plan：PR 可合并，无需再改代码。**

Agent 独立重跑命令与上表相同，结果 **3/3 PASS**：

| 用例 | Agent 终验 |
|------|------------|
| `test_03_draw_guess_core_flow` | ✅ |
| `test_13_draw_guess_insufficient_players` | ✅ |
| `test_03_draw_guess_member_display` | ✅ |

- `memberCountLine` 实测：`当前 3 人（至少 2 人可开始）`
- 报告：`minium-tests/outputs/report.html`
- 详细回执：[`DRAW_GUESS_PR_DELIVERY.md`](../DRAW_GUESS_PR_DELIVERY.md) §给 Coding Plan

**用户转话：**

```
Agent 终验 3/3 PASS，见 DRAW_GUESS_PR_DELIVERY.md，PR 可合并。
```

---

### 以后改你画我猜 / 类似分包游戏时的检查清单

- [ ] `feature-flags` 关闭时，**带 roomId 深链**是否仍能进房测 Minium？
- [ ] seed 后是否调 `refresh_lobby`（或等价 `_refresh_host`）？
- [ ] `push_view_to_page` 是否有 **Page 方法 + setData** 双路径？
- [ ] 改完分包后 **Cmd+B 编译**（CLI 无 compile 命令）
- [ ] suite：`suite_draw_guess.json` → **3/3 PASS**

### 历史待办（第一轮说明，已完成）

<details>
<summary>展开：第一轮 FAIL 现象与 Coding Plan checklist（存档）</summary>

**FAIL：** `test_03_draw_guess_member_display` — `page.data_value("memberCountLine")` 为 `None`（页面实际为 `''`，`data_value` 当无值）。

**Coding Plan checklist（A/B，已完成）：**

- A. `_patchViewFromSync` 优先 `v.publicPlayers`
- B. `test_member_display_format.py` seed 后 `refresh_lobby`

</details>

---

## 你每次改完必须交付

在 PR 描述或测试文档**末尾**粘贴（填好括号）：

```markdown
## Minium 验收 → 交给 Agent

- 游戏：（例：你画我猜 / 你比划我猜）
- suite：`minium-tests/suite_xxx.json`（没有就新建并登记到本文 §suite 表）
- 命令：
  cd /Users/haha/greatMan/minium-tests
  minitest -m testcases -c config.json -s suite_xxx.json -g
- 云函数：（例：drawRoomService）需已部署
- 通过标准：N/N，无 FAIL/ERROR
- 备注：（新 testid、__testSeedPlayers、已知跳过项等）

**状态：可以交给 Agent 跑 Minium 了**
```

最后一行 **「可以交给 Agent 跑 Minium 了」** 是用户转话的开关；没写这行 = 还没准备好测。

---

## 改代码时的约定

1. **优先走云函数建房 + `reLaunch` 进游戏页**（与现有 `DrawPage` / `test_gesture_final.py` 一致），少依赖首页点卡片。
2. **需要 UI 自动化点的控件** → 加 `data-testid="..."`（Canvas / 按钮），并在验收小节列出。
3. **需要多人/跳过倒计时** → 在云函数加 `_test: true` 守卫的 `__testSeedPlayers` 等（见 `minium-tests/README.md`）。
4. **Page Object 与测试参数一致** — 例如 `DrawPage.create_room()` 无 `difficulty` 参数，测试里勿乱传。
5. **feature-flags 与 Minium** — 游戏在首页关闭（`DRAW_GUESS_ENABLED=false`）时，**带 `roomId` 深链进房**仍须可测；见 §你画我猜 Minium 闭环 `onLoad` 豁免。`push_view_to_page` 建议保留 `setData` fallback（`cloud_helper.py`）。
6. **不要**在交付里让用户手跑 Minium；写清 suite 即可。

---

## suite 登记表（改完请更新）

| 游戏 | suite 文件 | 主要用例 |
|------|------------|----------|
| 全游戏回归 | `suite.json` | test_all_games + mystery + member_display |
| 你画我猜 | `suite_draw_guess.json` | test_03 / test_13 + member_display |
| 你比划我猜 | （项目内）`make minium` → `tests/test_gesture_final.py` | 见 `LOCAL_TEST_GUIDE.md` |

新增游戏：复制 `suite_draw_guess.json` 改 `case_list`，并在上表加一行。

---

## 相关路径

| 路径 | 用途 |
|------|------|
| `minium-tests/config.json` | `project_path`、`test_port: 9420` |
| `minium-tests/pages/*_page.py` | Page Object |
| `minium-tests/testcases/` | 用例 |
| `projects/wechat-mini/2026-04-26-family-party-games/` | 小程序源码 |

---

## 用户转给 Agent 的一句话（你可在 PR 里写好）

```
Coding Plan 改完了，按 minium-tests/CODING_PLAN.md 验收小节跑 Minium，suite 是 suite_xxx.json。
```

---

*与 Agent 分工详情：[`MINIUM_AGENT_HANDOFF.md`](./MINIUM_AGENT_HANDOFF.md)*
