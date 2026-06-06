# 你画我猜 Canvas 绘画同步 - Minium 验收交付

## Minium 验收（交给 Agent）

**游戏**：你画我猜（Canvas 绘画同步修复）

**suite**：`minium-tests/suite_draw_guess.json`

**命令**：
```bash
cd /Users/haha/greatMan/minium-tests
minitest -m testcases -c config.json -s suite_draw_guess.json -g
```

**前置检查**：
- ✅ 微信开发者工具已打开项目 `projects/wechat-mini/2026-04-26-family-party-games`
- ✅ 自动化端口 9420 已启用（`cli auto --project ... --auto-port 9420`）
- ✅ 云函数 `drawRoomService` 已部署（绿色）
- ✅ 编译无报错（Cmd+B）

**修复内容**：
- ✅ `_refreshCanvasRect()` - 改用 `fields({ rect: true })` 解决坐标偏移
- ✅ `_touchXY()` - 改进触摸坐标转换逻辑
- ✅ `scheduleInitCanvas()` - 避免重复初始化导致闪烁
- ✅ `onTouchE()` - 添加 `_debouncedSaveCanvas()` 防抖机制（200ms）
- ✅ `doEndG()` - 完整清理绘画状态（_allPaths、_curPath、_cseq）
- ✅ `onManualSync()` - 增强观看者同步能力

**已添加 data-testid**：
```
data-testid="enter-drawing"      - 进入绘画模式按钮
data-testid="manual-sync"        - 手动同步按钮
data-testid="end-game"           - 结束游戏按钮
data-testid="play-again"         - 再来一局按钮
```

**通过标准**：
- ✅ 3/3 测试用例全部 PASS（无 FAIL/ERROR）
- ✅ `test_03_draw_guess_core_flow` - 核心绘画流程
- ✅ `test_13_draw_guess_insufficient_players` - 人数不足校验
- ✅ `test_03_draw_guess_member_display` - 成员列表展示

**报告位置**：`minium-tests/outputs/report.html`

---

## 技术细节

### 修复的问题

| 问题 | 原因 | 修复 |
|------|------|------|
| **坐标偏移** | `boundingClientRect()` 相对视口，导航栏存在时偏差大 | 改用 `fields({ rect: true })` 获取绝对坐标 |
| **Canvas 闪烁** | `scheduleInitCanvas()` 被多处调用，导致重复初始化 | 加严格检查，仅在序列变化时初始化 |
| **笔画上传频繁** | 抬笔即上传，可能多次触发 | 添加 200ms 防抖 |
| **游戏结束未清理** | `doEndG()` 仅调用 `loadView()`，旧数据残留 | 完整清空 _allPaths、_curPath、_cseq、_canvasReadySeq |
| **观看者不同步** | `onManualSync()` 只适配绘画者 | 支持观看者触发重新同步 |

### Page Object 已验证

位置：`minium-tests/pages/draw_page.py`

```python
class DrawPage:
    def create_room(self)              # 创建房间
    def join_room(self, roomCode)      # 加入房间  
    def enter_drawing_mode(self)       # 进入绘画（tapById enter-drawing）
    def draw_line(self, x1, y1, x2, y2) # 绘制线条
    def manual_sync(self)              # 手动同步（tapById manual-sync）
    def end_game(self)                 # 结束游戏（tapById end-game）
```

---

## 参考文档

- 修复详情：`draw-guess-issues.md`
- 手动测试清单：`TEST-MANUAL-DRAW-GUESS.md`
- Coding Plan：`minium-tests/CODING_PLAN.md`
- Agent 执行手册：`minium-tests/MINIUM_AGENT_HANDOFF.md`

---

## Agent 终验（memberCountLine A–D + Canvas 套件）

- **suite：** `minium-tests/suite_draw_guess.json`
- **Agent 结果：** ✅ 3/3 PASS（2026-06-03）
- **memberCountLine：** `当前 3 人（至少 2 人可开始）`
- **报告：** `minium-tests/outputs/report.html`
- **回执：** 仓库根目录 [`DRAW_GUESS_PR_DELIVERY.md`](../../DRAW_GUESS_PR_DELIVERY.md) §给 Coding Plan

**PR 状态：✅ 可合并**（本 PR 已过「可以交给 Agent 跑 Minium 了」阶段）

---
