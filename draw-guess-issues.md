# 你画我猜 - 绘画同步问题诊断

## 问题清单

### 1. ❌ 画板坐标偏移（最严重）

**症状**：绘画时笔迹出现在错误位置，不是手指触摸的地方

**根本原因**：
- `_refreshCanvasRect()` 获取画布的 boundingClientRect
- 但 boundingClientRect 是**相对于视口**的坐标，不是相对于屏幕
- 当页面滚动或有其他 UI 覆盖时，坐标就不准确

**代码位置**：`draw-guess.js:396-412`
```javascript
_refreshCanvasRect (cb) {
  if (!wx.createSelectorQuery) {
    cb && cb()
    return
  }
  wx.createSelectorQuery()
    .in(this)
    .select('#cvs2')
    .boundingClientRect()  // ← 这个坐标不准确！
    .exec((res) => {
      if (res && res[0]) {
        this._canvasRect = res[0]  // { top, left, width, height, right, bottom }
      }
      if (cb) { cb() }
    })
}
```

**问题细节**：
- `boundingClientRect()` 返回相对于**视口**的坐标
- 如果画布不在视口顶部（有导航栏/标题栏），`top` 和 `left` 会有偏移
- 页面有 `navigationBar` 时，这个偏移会导致触摸坐标完全错误

### 2. ❌ 坐标转换不完整

**症状**：即使画板位置对了，有时候笔迹还是歪

**根本原因**：`_touchXY()` 只做了简单的减法，没考虑到：
- Canvas 的 DPR（设备像素比）
- Canvas 的实际绘制尺寸 vs 显示尺寸

**代码位置**：`draw-guess.js:414-429`
```javascript
_touchXY (t0) {
  const r = this._canvasRect
  if (!t0) {
    return null
  }
  if (r && t0.clientX != null && t0.clientY != null) {
    return {
      x: t0.clientX - r.left,  // ← 简单的减法，没考虑 DPR
      y: t0.clientY - r.top
    }
  }
  if (t0.x != null && t0.y != null) {
    return { x: t0.x, y: t0.y }
  }
  return null
}
```

**缺失的逻辑**：
```javascript
// 应该考虑
const dpr = wx.getSystemInfoSync().pixelRatio || 2
const x = (t0.clientX - r.left) * dpr
const y = (t0.clientY - r.top) * dpr
```

### 3. ❌ 多次初始化 Canvas 导致的闪烁

**症状**：画的过程中画板会闪烁、抖动

**根本原因**：
- `scheduleInitCanvas()` 被多个地方调用（11 处！）
- 每次调用都会重新初始化 Canvas，导致之前的内容被清空
- `_canvasReadySeq` 用来防止重复初始化，但检查逻辑不够严密

**代码位置**：`draw-guess.js:1315-1328`
```javascript
scheduleInitCanvas () {
  const s = this.data.state
  if (!this._shouldInitCanvas() || !s) {
    return
  }
  const seq = s.canvasSeq | 0
  if (this._canvasReadySeq === seq && this._cvs) {
    // ← 这里只检查了 seq，没有检查绘画状态
    // 即使 seq 相同，如果 isDrawingMode 改变了也应该重新初始化
    const st = this.data.state
    if (st) {
      this._onGameStateCanvas(st)
    }
    return
  }
  // 延迟 200ms 再初始化，容易被打断
  setTimeout(() => this.initCanvas2d(0), 200)
}
```

### 4. ❌ 笔画上传不及时（已禁用，但逻辑有问题）

**症状**：网络卡顿时，观看者看不到最新的笔画

**现状**：
```javascript
// draw-guess.js:1489
setupUploadLoop () {
  /* 笔画同步见 _queueStrokeUpload；不再每 500ms 传整图，减轻延迟与体积 */
}
```
已经注释掉了，改为在 `onTouchE`（抬笔）时上传：
```javascript
onTouchE () {
  // ...
  this.saveCanvasToCloud()  // 只在抬笔时上传一次
}
```

**问题**：
- 如果绘画流不顺（手指抖动），可能会有多个 `onTouchE` 事件
- 但没有防抖，可能导致频繁上传
- 观看者看到的笔画会是跳跃的，而不是流畅的

### 5. ❌ 观看者画板不同步

**症状**：观看者（非绘画者）看到的画板与实际不符

**根本原因**：`onCanvasDataChange()` 的处理不完整

**代码位置**：`draw-guess.js:284-295`
```javascript
onCanvasDataChange (paths, seq) {
  if (!paths || !paths.length) {
    if ((seq | 0) !== (this._replayedSeq | 0)) {
      this.redrawCanvas([], seq)
    }
    return
  }
  if (this.data.isMeDrawer && this.data.isDrawingMode) {
    return  // ← 绘画者不应该处理这个事件
  }
  this.redrawCanvas(paths, seq)
}
```

**问题**：
- 观看者在 `_onGameStateCanvas()` 中被动接收数据
- 如果网络延迟或丢包，观看者看不到最新的笔画
- 没有"请求重新同步"的机制

### 6. ❌ 游戏结束后没有清理状态

**症状**：再来一局时，前一局的画还在

**根本原因**：`doEndG()` 和 `onClear()` 清理逻辑不完整

**代码位置**：`draw-guess.js:997-1002`
```javascript
doEndG () {
  callDraw(
    { action: 'endGame', roomId: this.data.roomId },
    { onOk: () => { this.loadView() } }
  )
}
```

**缺失**：
- 没有清空 `this._allPaths` 和 `this._curPath`
- 没有清空画布 `this.clearLocalCanvas()`
- 下一轮开始时旧画会残留

---

## 优先级修复清单

### 高优先级（影响可用性）

#### 1️⃣ 修复坐标偏移
```javascript
// 改进 _refreshCanvasRect
_refreshCanvasRect (cb) {
  if (!wx.createSelectorQuery) {
    cb && cb()
    return
  }
  wx.createSelectorQuery()
    .in(this)
    .select('#cvs2')
    .fields({ node: true, size: true, rect: true })  // ← 加上 rect
    .exec((res) => {
      if (res && res[0]) {
        const rect = res[0]
        // 相对于屏幕的绝对坐标
        this._canvasRect = {
          left: rect.left || 0,
          top: rect.top || 0,
          width: rect.width || 280,
          height: rect.height || 400,
          right: (rect.left || 0) + (rect.width || 280),
          bottom: (rect.top || 0) + (rect.height || 400)
        }
      }
      cb && cb()
    })
}
```

#### 2️⃣ 修复触摸坐标转换
```javascript
// 改进 _touchXY，考虑 DPR 和实际坐标
_touchXY (t0) {
  const r = this._canvasRect
  if (!t0 || !r) {
    return null
  }
  
  let x = 0, y = 0
  if (t0.clientX != null && t0.clientY != null) {
    x = t0.clientX - (r.left || 0)
    y = t0.clientY - (r.top || 0)
  } else if (t0.x != null && t0.y != null) {
    x = t0.x
    y = t0.y
  } else {
    return null
  }
  
  // 不需要乘以 DPR，因为我们在 canvas.getContext('2d') 后已经设置过 scale
  return { x, y }
}
```

#### 3️⃣ 防止 Canvas 重复初始化
```javascript
// 改进 scheduleInitCanvas
scheduleInitCanvas () {
  const s = this.data.state
  if (!this._shouldInitCanvas() || !s) {
    return
  }
  
  const seq = s.canvasSeq | 0
  const drawing = this.data.isDrawingMode && this.data.isMeDrawer
  
  // 如果已经初始化过这个序列，且正在绘画，就不要重新初始化
  if (
    this._canvasReadySeq === seq && 
    this._cvs && 
    !drawing
  ) {
    return
  }
  
  // 立即初始化，不要延迟（已在前面检查过条件）
  this.initCanvas2d(0)
}
```

#### 4️⃣ 游戏结束时完整清理
```javascript
// 改进 doEndG
doEndG () {
  callDraw(
    { action: 'endGame', roomId: this.data.roomId },
    {
      onOk: () => {
        // 清理绘画状态
        this._exitDrawingMode(true)
        this.clearLocalCanvas()
        this._allPaths = []
        this._curPath = null
        this.loadView()
      }
    }
  )
}
```

### 中优先级（改善体验）

#### 5️⃣ 加入笔画防抖
```javascript
// 改进 saveCanvasToCloud，防止频繁上传
_debouncedSaveCanvas() {
  if (this._saveCanvasTimer) {
    clearTimeout(this._saveCanvasTimer)
  }
  this._saveCanvasTimer = setTimeout(() => {
    this.saveCanvasToCloud()
    this._saveCanvasTimer = null
  }, 300)  // 300ms 防抖
}

onTouchE () {
  this._touching = false
  this._last = null
  if (this._curPath && this._curPath.pts && this._curPath.pts.length >= 2) {
    this._allPaths.push(this._curPath)
  }
  this._curPath = null
  this._debouncedSaveCanvas()  // 用防抖替代直接调用
}
```

#### 6️⃣ 加入同步重试机制
```javascript
// 在观看者端，加入"请求重新同步"的能力
onManualSync () {
  if (!this.data.isMeDrawer && this.data.inDrawingPhase) {
    // 观看者可以手动要求重新同步一次画布
    this._refreshRoomState()
    wx.showToast({ title: '已重新同步', icon: 'success' })
  }
}
```

### 低优先级（长期优化）

#### 7️⃣ 支持本地笔画缓存
- 在 `redrawCanvas` 时同时缓存到本地，防止网络抖动导致画布清空

#### 8️⃣ 增量笔画同步
- 目前是全量同步所有笔画，可以改为只同步新增的笔画（需要云端支持）

---

## 完整性缺陷总结

| 阶段 | 问题 | 严重程度 | 修复工作量 |
|------|------|--------|---------|
| 初始化 | Canvas 多次重复初始化 | 🔴 高 | 小 |
| 绘画 | 坐标偏移导致笔迹错位 | 🔴 高 | 中 |
| 绘画 | 没有考虑 DPR 缩放 | 🟠 中 | 小 |
| 上传 | 笔画上传不及时/频率不当 | 🟠 中 | 小 |
| 同步 | 观看者看不到最新画 | 🟠 中 | 中 |
| 结束 | 没有完整清理状态 | 🟠 中 | 小 |
| UI | 没有"再来一局"按钮 | 🟡 低 | 小 |

---

## 测试建议

修复后应该验证：
1. ✅ 单人画板在绘画时笔迹准确（用指尖点不同位置验证）
2. ✅ 多人画板实时同步（观看者看到的画与绘画者一致）
3. ✅ 快速绘画不卡顿（画速快时画板不闪烁）
4. ✅ 网络延迟情况下画板不消失（模拟弱网测试）
5. ✅ 再来一局时前一局的画完全清空
6. ✅ 从不同角度（竖屏/横屏/不同分辨率）测试坐标准确性

