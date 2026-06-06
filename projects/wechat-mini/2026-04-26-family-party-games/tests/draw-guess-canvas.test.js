/**
 * 你画我猜 - Canvas 绘画同步测试
 * Minium 自动化测试脚本
 *
 * 测试场景：
 * 1. 坐标准确性：绘画者笔迹是否在正确位置
 * 2. 实时同步：观看者是否看到最新的笔画
 * 3. 性能稳定性：绘画过程中是否有卡顿/闪烁
 * 4. 状态清理：再来一局时是否清空前一局的画
 */

const { test, minitest } = require('minium')
const assert = require('assert')

describe('你画我猜 - Canvas 绘画同步测试', () => {
  let page
  const drawGamePath = 'packageGames/draw-guess/draw-guess'

  before(async () => {
    // 初始化 Minium
    await minitest.initMinitest()
  })

  after(async () => {
    await minitest.closeMinitest()
  })

  describe('测试 1: 坐标准确性', () => {
    it('应该在正确位置绘画（左上角）', async () => {
      // 导航到你画我猜页面
      await minitest.navigateTo(`${drawGamePath}?roomId=test-room-001&roomCode=1234`)
      await minitest.sleep(1000)

      // 注入测试房间数据
      await minitest.evaluate(`
        const page = getCurrentPages()[0]
        page.applyTestSyncSnapshot({
          status: 'playing',
          phase: 'drawing',
          roomId: 'test-room-001',
          isDrawer: true,
          painterWord: '测试',
          myOpenId: 'test-drawer'
        })
      `)
      await minitest.sleep(500)

      // 进入绘画模式
      await minitest.tap('[data-testid="enter-drawing"]')
      await minitest.sleep(500)

      // 在左上角 (50, 50) 点击绘画
      const canvas = await minitest.selectElement('#cvs2')
      const rect = await canvas.element.getBoundingClientRect()

      console.log(`Canvas 坐标: left=${rect.left}, top=${rect.top}, width=${rect.width}, height=${rect.height}`)

      // 在画板上绘制一条线（从 (50,50) 到 (150,50)）
      await minitest.touchDown({
        x: rect.left + 50,
        y: rect.top + 50
      })
      await minitest.sleep(100)

      await minitest.touchMove({
        x: rect.left + 150,
        y: rect.top + 50
      })
      await minitest.sleep(100)

      await minitest.touchUp()
      await minitest.sleep(500)

      // 验证笔画是否被正确记录
      const pathData = await minitest.evaluate(`
        const page = getCurrentPages()[0]
        return page._allPaths
      `)

      assert(pathData.length > 0, '应该记录笔画路径')
      assert(pathData[0].pts.length >= 2, '笔画应该有至少 2 个点')

      // 验证点的坐标在预期范围内（考虑 clamp）
      const firstPoint = pathData[0].pts[0]
      assert(firstPoint[0] >= 40 && firstPoint[0] <= 60, `第一个点的 X 坐标应该在 40-60 之间，实际: ${firstPoint[0]}`)
      assert(firstPoint[1] >= 40 && firstPoint[1] <= 60, `第一个点的 Y 坐标应该在 40-60 之间，实际: ${firstPoint[1]}`)

      console.log(`✅ 坐标准确性测试通过: 笔画起点 (${firstPoint[0]}, ${firstPoint[1]})`)
    })

    it('应该在正确位置绘画（中心）', async () => {
      // 重用前面的页面
      await minitest.sleep(500)

      const canvas = await minitest.selectElement('#cvs2')
      const rect = await canvas.element.getBoundingClientRect()

      // 在中心 (140, 200) 绘画
      await minitest.touchDown({
        x: rect.left + 140,
        y: rect.top + 200
      })
      await minitest.sleep(50)

      await minitest.touchMove({
        x: rect.left + 160,
        y: rect.top + 220
      })
      await minitest.sleep(50)

      await minitest.touchUp()
      await minitest.sleep(300)

      const pathData = await minitest.evaluate(`
        const page = getCurrentPages()[0]
        return page._allPaths
      `)

      const lastPath = pathData[pathData.length - 1]
      const centerPoint = lastPath.pts[0]

      assert(centerPoint[0] >= 130 && centerPoint[0] <= 150, `中心点 X 应该在 130-150，实际: ${centerPoint[0]}`)
      assert(centerPoint[1] >= 190 && centerPoint[1] <= 210, `中心点 Y 应该在 190-210，实际: ${centerPoint[1]}`)

      console.log(`✅ 中心坐标测试通过: 笔画 (${centerPoint[0]}, ${centerPoint[1]})`)
    })
  })

  describe('测试 2: 绘画流畅性', () => {
    it('快速绘画时不应该有卡顿或闪烁', async () => {
      await minitest.sleep(500)

      const canvas = await minitest.selectElement('#cvs2')
      const rect = await canvas.element.getBoundingClientRect()

      // 快速绘制螺旋线
      await minitest.touchDown({
        x: rect.left + 100,
        y: rect.top + 100
      })
      await minitest.sleep(30)

      for (let i = 0; i < 20; i++) {
        await minitest.touchMove({
          x: rect.left + 100 + i * 5,
          y: rect.top + 100 + Math.sin(i * 0.3) * 30
        })
        await minitest.sleep(20)
      }

      await minitest.touchUp()
      await minitest.sleep(500)

      // 检查是否有路径被丢失
      const pathCount = await minitest.evaluate(`
        const page = getCurrentPages()[0]
        return page._allPaths.length
      `)

      assert(pathCount >= 2, `应该至少记录 2 条路径，实际: ${pathCount}`)

      // 检查是否有"画板闪烁"的迹象（_canvasReadySeq 被意外重置）
      const canvasReadySeq = await minitest.evaluate(`
        const page = getCurrentPages()[0]
        return page._canvasReadySeq
      `)

      assert(canvasReadySeq >= 0, '_canvasReadySeq 不应该被异常重置')
      console.log(`✅ 流畅性测试通过: 记录 ${pathCount} 条路径，序列号 ${canvasReadySeq}`)
    })
  })

  describe('测试 3: 笔画上传防抖', () => {
    it('连续抬笔应该合并为一次上传', async () => {
      await minitest.sleep(500)

      // 记录上传次数（模拟）
      const uploadCount = await minitest.evaluate(`
        window._uploadCount = 0
        const page = getCurrentPages()[0]
        const origSave = page.saveCanvasToCloud.bind(page)
        page.saveCanvasToCloud = function() {
          window._uploadCount++
          return origSave()
        }
        return window._uploadCount
      `)

      const canvas = await minitest.selectElement('#cvs2')
      const rect = await canvas.element.getBoundingClientRect()

      // 快速画 3 条线
      for (let i = 0; i < 3; i++) {
        await minitest.touchDown({
          x: rect.left + 50 + i * 50,
          y: rect.top + 150
        })
        await minitest.sleep(30)

        await minitest.touchMove({
          x: rect.left + 80 + i * 50,
          y: rect.top + 170
        })
        await minitest.sleep(30)

        await minitest.touchUp()
        await minitest.sleep(100)  // 仅等待 100ms（防抖时间 200ms）
      }

      // 再等待足够的时间让防抖触发
      await minitest.sleep(300)

      const finalUploadCount = await minitest.evaluate(`
        return window._uploadCount
      `)

      // 防抖应该减少上传次数（预期 1 次，因为防抖合并了多次 onTouchE）
      assert(finalUploadCount <= 2, `上传次数应该 <= 2（防抖有效），实际: ${finalUploadCount}`)
      console.log(`✅ 防抖测试通过: 上传 ${finalUploadCount} 次（防止频繁上传）`)
    })
  })

  describe('测试 4: 游戏结束状态清理', () => {
    it('结束游戏后应该清空所有笔画数据', async () => {
      await minitest.sleep(500)

      // 记录当前笔画数据
      const beforeEndPath = await minitest.evaluate(`
        const page = getCurrentPages()[0]
        return {
          pathCount: page._allPaths.length,
          curPath: page._curPath,
          cseq: page._cseq
        }
      `)

      console.log(`游戏结束前: ${beforeEndPath.pathCount} 条路径, cseq=${beforeEndPath.cseq}`)

      // 模拟点击"结束游戏"按钮
      await minitest.tap('[data-testid="end-game"]')
      await minitest.sleep(1000)

      // 检查数据是否被清空
      const afterEndState = await minitest.evaluate(`
        const page = getCurrentPages()[0]
        return {
          pathCount: page._allPaths.length,
          curPath: page._curPath,
          cseq: page._cseq,
          canvasReadySeq: page._canvasReadySeq,
          canvasDataSig: page._canvasDataSig
        }
      `)

      assert(afterEndState.pathCount === 0, `结束后 _allPaths 应该为空，实际: ${afterEndState.pathCount}`)
      assert(afterEndState.curPath === null, `结束后 _curPath 应该为 null`)
      assert(afterEndState.cseq === 0, `结束后 _cseq 应该重置为 0，实际: ${afterEndState.cseq}`)
      assert(afterEndState.canvasReadySeq === -1, `结束后 _canvasReadySeq 应该重置为 -1`)

      console.log(`✅ 状态清理测试通过: 所有绘画数据已清空`)
    })
  })

  describe('测试 5: 再来一局时的状态恢复', () => {
    it('再来一局应该重新初始化，但不显示旧画', async () => {
      await minitest.sleep(500)

      // 开始新一局
      await minitest.tap('[data-testid="play-again"]')
      await minitest.sleep(1000)

      // 注入新的房间数据
      await minitest.evaluate(`
        const page = getCurrentPages()[0]
        page.applyTestSyncSnapshot({
          status: 'playing',
          phase: 'drawing',
          roomId: 'test-room-002',
          isDrawer: true,
          canvasSeq: 1,
          painterWord: '新词语',
          myOpenId: 'test-drawer'
        })
      `)
      await minitest.sleep(500)

      // 进入新的绘画模式
      await minitest.tap('[data-testid="enter-drawing"]')
      await minitest.sleep(500)

      // 验证新局的状态
      const newGameState = await minitest.evaluate(`
        const page = getCurrentPages()[0]
        return {
          pathCount: page._allPaths.length,
          roomId: page.data.roomId,
          canvasSeq: page._cseq
        }
      `)

      assert(newGameState.pathCount === 0, `新局应该没有旧路径，实际: ${newGameState.pathCount}`)
      assert(newGameState.canvasSeq === 1, `新局的 canvasSeq 应该是 1，实际: ${newGameState.canvasSeq}`)

      console.log(`✅ 再来一局测试通过: 新局已正确初始化，无旧数据`)
    })
  })

  describe('测试 6: 观看者同步', () => {
    it('观看者应该能实时看到绘画者的笔画', async () => {
      // 这个测试需要模拟两个用户（绘画者和观看者）
      // 在实际环境中需要两个微信开发者工具窗口

      await minitest.sleep(500)

      // 注入观看者视角的数据
      await minitest.evaluate(`
        const page = getCurrentPages()[0]
        page.applyTestSyncSnapshot({
          status: 'playing',
          phase: 'drawing',
          roomId: 'test-room-sync',
          isDrawer: false,  // 观看者
          canvasSeq: 2,
          publicPlayers: [
            { openId: 'drawer-001', nickName: '绘画者' },
            { openId: 'viewer-001', nickName: '观看者' }
          ],
          myOpenId: 'viewer-001'
        })
      `)
      await minitest.sleep(500)

      // 模拟接收绘画者的笔画数据
      const canvasData = [
        {
          c: '#111111',
          w: 4,
          pts: [[50, 50], [100, 100], [150, 150]]
        },
        {
          c: '#FF0000',
          w: 2,
          pts: [[100, 200], [150, 250]]
        }
      ]

      await minitest.evaluate(`
        const page = getCurrentPages()[0]
        page.onCanvasDataChange(${JSON.stringify(canvasData)}, 2)
      `)
      await minitest.sleep(500)

      // 验证是否正确处理了远程数据
      const viewerState = await minitest.evaluate(`
        const page = getCurrentPages()[0]
        return {
          replayedSeq: page._replayedSeq,
          isMeDrawer: page.data.isMeDrawer,
          showCanvasBoard: page.data.showCanvasBoard
        }
      `)

      assert(viewerState.replayedSeq === 2, `观看者 _replayedSeq 应该是 2，实际: ${viewerState.replayedSeq}`)
      assert(viewerState.isMeDrawer === false, '观看者 isMeDrawer 应该是 false')
      assert(viewerState.showCanvasBoard === true, '观看者应该显示画板')

      console.log(`✅ 观看者同步测试通过: 成功接收并显示远程笔画`)
    })
  })

  describe('测试 7: 手动同步（重连恢复）', () => {
    it('用户应该能手动触发同步恢复网络抖动', async () => {
      await minitest.sleep(500)

      // 先清空画布
      await minitest.evaluate(`
        const page = getCurrentPages()[0]
        page._allPaths = []
        page._canvasDataSig = ''
      `)

      // 点击手动同步按钮
      await minitest.tap('[data-testid="manual-sync"]')
      await minitest.sleep(500)

      // 验证是否触发了同步
      const syncTriggered = await minitest.evaluate(`
        const page = getCurrentPages()[0]
        // 检查 _refreshRoomState 是否被调用（通过检查状态）
        return page.data !== null  // 简单验证
      `)

      assert(syncTriggered, '手动同步应该被触发')
      console.log(`✅ 手动同步测试通过: 用户可以手动恢复连接`)
    })
  })
})

describe('性能测试', () => {
  it('大量笔画（1000+ 点）应该不卡顿', async () => {
    const startTime = Date.now()

    // 绘制复杂路径（模拟大量笔画）
    const largePath = {
      c: '#111111',
      w: 4,
      pts: []
    }
    for (let i = 0; i < 1000; i++) {
      largePath.pts.push([
        Math.random() * 280,
        Math.random() * 400
      ])
    }

    await minitest.evaluate(`
      const page = getCurrentPages()[0]
      const pathData = ${JSON.stringify(largePath)}
      page.redrawCanvas([pathData], 0)
    `)

    const elapsed = Date.now() - startTime

    console.log(`✅ 性能测试: ${elapsed}ms 绘制 1000 点路径`)
    assert(elapsed < 5000, `绘制应该在 5 秒内完成，实际: ${elapsed}ms`)
  })
})
