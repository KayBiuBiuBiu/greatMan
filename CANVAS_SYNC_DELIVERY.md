# Canvas 实时同步交付 — Agent 回归 ✅ 3/3 PASS

> **日期**: 2026-06-03  
> **功能**: 你画我猜 Canvas 双端实时同步（A 端画笔 → B 端实时看）  
> **状态**: Minium 自动化验收通过，Canvas 实时性需手测

---

## 改动清单

| 项 | 文件 | 改动 | 行数 | 状态 |
|---|------|------|------|------|
| **A** | `drawRoomService/index.js` | getView 返回 gameState.canvasData | 1118–1127 | ✅ 合并 |
| **B** | `draw-guess.js` | _patchViewFromSync 接收并重绘 Canvas | 678–708 | ✅ 合并 |
| **C1** | `draw-guess.js` | 加 _lastCanvasDataVer 版本号字段 | 169 | ✅ 合并 |
| **C2** | `draw-guess.js` | Canvas 轮询改 500ms | 332 | ✅ 合并 |
| **C3** | `draw-guess.js` | doEndG 清理版本号 | 1038 | ✅ 合并 |
| **C4** | `draw-guess.js` | _onCanvasSeqChange 轮转清理 | 1189 | ✅ 合并 |

---

## Agent 回归结果

### Minium 自动化验收 ✅ 3/3 PASS

```bash
cd /Users/haha/greatMan/minium-tests
minitest -m testcases -c config.json -s suite_draw_guess.json -g
```

**测试结果**：

| 用例 | 结果 | 备注 |
|------|------|------|
| `test_03_draw_guess_core_flow` | ✅ PASS | 游戏流程无退化 |
| `test_13_draw_guess_insufficient_players` | ✅ PASS | 人数校验正常 |
| `test_03_draw_guess_member_display` | ✅ PASS | memberCountLine: "当前 3 人（至少 2 人可开始）" |

- **汇总**: `failed num:0, error num:0`
- **无退化**: Canvas 同步改后 memberCountLine 仍正常（回归通过）
- **报告**: `minium-tests/outputs/report.html`

---

## Canvas 双端实时性

### ✅ 已实现（代码侧）

1. **云端数据流**
   - A 抬笔 → `saveCanvasToCloud()` → 云函数 `updateCanvas`
   - 存入 `gameState.canvasData`、`canvasDataVer`

2. **网络同步**
   - B 每 500ms 轮询 `getView()`
   - 云函数返回 `view.gameState.canvasData`

3. **前端应用**
   - `_patchViewFromSync()` 接收 Canvas
   - 版本号对比 `cver !== this._lastCanvasDataVer`
   - 版本更新时调 `redrawCanvas()`

4. **状态管理**
   - 每轮开始 `_onCanvasSeqChange()` 重置版本号
   - 游戏结束 `doEndG()` 清理版本号
   - 避免轮次串联

### ⚠️ 手测覆盖（Minium 未支持）

**为什么 Minium 无法覆盖**：
- Minium 框架操纵的是自动化页面（单实例）
- 无法同时控制两个独立的 Canvas 画板
- 无法模拟 A 端真实绘画的多笔操作
- 版本号变化无法精确验证

**建议手测清单**：

```
□ 开始游戏
  ├─ 两台手机同房，A 为画家，B 为猜者
  └─ 都看到"当前 X 人"提示
  
□ Canvas 实时性
  ├─ A 点「开始绘画」→ 进入画板（本地即时反馈）
  ├─ B 观察 Canvas 板
  ├─ A 开始拖动笔（在 B 屏幕上看）
  ├─ 验证：笔画出现延迟 < 1s ✓
  └─ 笔迹流畅，无倒流/混乱 ✓

□ 多轮切换
  ├─ 一轮结束，出现「下一轮」按钮
  ├─ 点击后，A 和 B 的 Canvas 都清空 ✓
  ├─ 下一轮 A 重新绘画
  └─ B 看到新的 Canvas 不含上轮笔画 ✓

□ 快速笔画
  ├─ A 快速连续画多条线
  ├─ B 看笔画是否跟得上（无漏笔） ✓
  └─ 多笔之间是否有串联 ✓

□ 网络延迟模拟
  ├─ 在 B 端网络中添加 500ms 延迟（可选）
  ├─ 验证总延迟仍可控 ✓
  └─ 是否有丢笔现象 ✓
```

---

## 延迟分析

### 预期延迟分解

```
A 端：抬笔 → 防抖 → 上传 → 云函数处理
      |      200ms    |      ~100ms
      └──────────────┬────────────┘
                     v
            gameState.canvasData
                     │
                B 轮询周期（随机 0-500ms）
                     │
              拉 getView → 云函数查询 → 返回数据
              |         ~100ms      |
              └─────────────┬───────┘
                           v
                  _patchViewFromSync
                      检查版本号
                  redrawCanvas ← 看到 ✓
                  
总延迟 ≈ 200ms + (0-500)ms + 100ms = 300-800ms
预期平均 ≈ 500-600ms（接近实时）
```

---

## 代码亮点

### 1. 版本号去重机制

```javascript
// draw-guess.js 行 687–691
if (cver !== this._lastCanvasDataVer) {
  this._lastCanvasDataVer = cver
  this.redrawCanvas(v.gameState.canvasData, cver)
}
```

**作用**：避免连续轮询拿到相同 Canvas 数据时的重复渲染，减少不必要的 CPU 消耗。

### 2. 轮次清理

```javascript
// draw-guess.js 行 1189
if (this._cseq !== seq) {
  this._lastCanvasDataVer = -1  // ← 新轮重置
  // ... 其他清理 ...
}
```

**作用**：每轮开始时将版本号重置为 -1，确保新的 Canvas 被接收，避免上轮数据串联。

### 3. 角色隔离

```javascript
// draw-guess.js 行 685
if (v.gameState && v.gameState.canvasData && v.phase === 'drawing' && !v.isDrawer) {
  // 只猜者端重绘
}
```

**作用**：画家端有本地即时反馈（主动绘画），猜者端才需从云端拉取 Canvas。

---

## 改动对其他功能的影响

### ✅ memberCountLine（前次修复）
- 不受影响（Canvas 同步是独立逻辑）
- Minium 验收仍 **3/3 PASS**

### ✅ 其他游戏
- `draw-guess.js` 改动不涉及其他游戏
- 云函数改动仅在 `phase === 'drawing'` 时返回 Canvas
- 其他游戏无 Canvas 同步需求

### ✅ 性能
- 轮询改 500ms（vs 1000ms）：增加 API 调用 2 倍
- 版本号去重：减少不必要的 redrawCanvas 调用
- 净效果：**轻微增加服务器负载，可接受**

---

## 后续建议

### 🎯 立即可做
- ✅ 合并到主线（Minium 回归通过）
- ✅ 上线测试版本，收集两端实时性反馈

### 🔄 中期优化（可选）
1. **WebSocket 替代轮询**
   - 降延迟到 100-200ms
   - 成本：后端改造、运维复杂度增加
   - 建议：若用户反馈延迟不可接受再做

2. **Canvas 增量同步**
   - 当前：全量 Canvas 数据
   - 优化：只同步新增笔画（增量）
   - 成本：编码复杂度高，效果有限

3. **手机性能优化**
   - 渲染优化：使用 requestAnimationFrame
   - 当前：同步调 redrawCanvas，可能阻塞

### 📝 文档更新
- 见 `docs/DRAW_GUESS_DB.md`（建议补充 Canvas 同步设计）

---

## Commits

| Commit | 说明 | 日期 |
|--------|------|------|
| `69be351` | Canvas 实时同步 | 2026-06-03 |
| `cef1da2` | memberCountLine 修复 + Minium 闭环 | 2026-06-03 |

---

## 核对清单

- [x] 云函数 getView 返回 Canvas 数据
- [x] 前端 _patchViewFromSync 接收并重绘
- [x] 版本号对比去重
- [x] 轮次清理（无串联）
- [x] 游戏结束清理
- [x] Canvas 轮询改 500ms
- [x] Minium 回归 3/3 PASS（无退化）
- [x] memberCountLine 仍正常
- [ ] ⚠️ Canvas 双端实时性手测（待用户验证）

---

**状态**: ✅ Minium 验收通过，PR 可合并。Canvas 实时性需手测，不阻塞合并。
