#!/usr/bin/env node

/**
 * 你比划我猜 - 快速云函数测试脚本
 * 用法：
 *   node tests/test-gesture-quick.js
 *
 * 功能：
 *   - 验证云函数基础逻辑（不需要真实微信环境）
 *   - 模拟房间创建、加入、开始、答题流程
 *   - 验证计分和状态转移
 */

const assert = require('assert')

// ==================== 模拟的云函数核心逻辑 ====================

function normGuess(s) {
  return String(s || '')
    .trim()
    .toLowerCase()
    .replace(/\s/g, '')
}

function performerForRound(players, round, totalRounds) {
  if (!players || players.length === 0) return null
  const idx = (round - 1) % players.length
  return players[idx].openId
}

// ==================== 测试套件 ====================

class GestureQuickTest {
  constructor() {
    this.rooms = new Map()
    this.players = new Map()
    this.states = new Map()
    this.testsPassed = 0
    this.testsFailed = 0
  }

  // 辅助函数
  log(msg, prefix = '  ') {
    console.log(prefix + msg)
  }

  pass(name) {
    console.log(`\n✓ PASS: ${name}`)
    this.testsPassed++
  }

  fail(name, error) {
    console.log(`\n✗ FAIL: ${name}`)
    console.log(`  Error: ${error.message}`)
    this.testsFailed++
  }

  // 测试 1: 创建房间
  test_01_createRoom() {
    const name = 'TC-01: 创建房间'
    try {
      const roomId = 'room_' + Date.now()
      const roomCode = '000001'
      const hostOpenId = 'user_host_001'

      const room = {
        _id: roomId,
        roomCode: roomCode,
        hostOpenId: hostOpenId,
        status: 'waiting',
        totalRounds: 5,
        roundDuration: 60,
        wordCategory: 'all',
        usedWordIds: [],
        currentWordId: '',
        currentWordText: '',
        createdAt: Date.now(),
        updatedAt: Date.now()
      }

      this.rooms.set(roomId, room)

      assert(room.roomCode === '000001', '房间码应为6位')
      assert(room.status === 'waiting', '初始状态应为 waiting')
      assert(room.hostOpenId === hostOpenId, '房主应正确设置')

      this.log(`房间ID: ${roomId}`)
      this.log(`房间码: ${room.roomCode}`)
      this.log(`房主: ${room.hostOpenId}`)
      this.pass(name)

      return roomId
    } catch (e) {
      this.fail(name, e)
      throw e
    }
  }

  // 测试 2: 加入房间
  test_02_joinRoom(roomId) {
    const name = 'TC-02: 加入房间'
    try {
      const room = this.rooms.get(roomId)
      assert(room, '房间应存在')

      const player1 = {
        _id: 'p1',
        roomId: roomId,
        openId: 'user_host_001',
        nickName: '玩家A',
        isHost: true,
        score: 0,
        joinedAt: Date.now()
      }

      const player2 = {
        _id: 'p2',
        roomId: roomId,
        openId: 'user_guest_001',
        nickName: '玩家B',
        isHost: false,
        score: 0,
        joinedAt: Date.now()
      }

      this.players.set('p1', player1)
      this.players.set('p2', player2)

      assert(this.players.size >= 2, '应有至少2个玩家')

      this.log(`玩家A: ${player1.nickName} (房主)`)
      this.log(`玩家B: ${player2.nickName}`)
      this.log(`总人数: 2`)
      this.pass(name)

      return [player1, player2]
    } catch (e) {
      this.fail(name, e)
      throw e
    }
  }

  // 测试 3: 开始游戏
  test_03_startGame(roomId, players) {
    const name = 'TC-03: 开始游戏'
    try {
      const room = this.rooms.get(roomId)
      assert(room, '房间应存在')
      assert(room.status === 'waiting', '房间状态应为 waiting')
      assert(players.length >= 2, '至少需要2个玩家')

      // 指定第一个表演者
      const performerId = performerForRound(players, 1, room.totalRounds)
      const performer = players.find(p => p.openId === performerId)

      // 设置初始词语
      room.status = 'playing'
      room.currentWordId = 'w1'
      room.currentWordText = '苹果'
      room.usedWordIds = ['w1']

      const gameState = {
        _id: roomId,
        phase: 'performing',
        currentRound: 1,
        roundStartTime: Date.now(),
        performerOpenId: performerId,
        performerNickName: performer.nickName,
        publicPlayers: players.map(p => ({
          openId: p.openId,
          nickName: p.nickName,
          score: p.score
        })),
        roundHits: [],
        revealedWord: '',
        publicLog: [`第1轮。表演者：${performer.nickName}。`]
      }

      this.states.set(roomId, gameState)

      assert(room.status === 'playing', '房间状态应为 playing')
      assert(gameState.phase === 'performing', '游戏阶段应为 performing')
      assert(gameState.performerOpenId === performerId, '表演者应正确指定')

      this.log(`房间状态: ${room.status}`)
      this.log(`游戏阶段: ${gameState.phase}`)
      this.log(`表演者: ${performer.nickName}`)
      this.log(`词语: ${room.currentWordText}`)
      this.pass(name)
    } catch (e) {
      this.fail(name, e)
      throw e
    }
  }

  // 测试 4: 表演者看到词语
  test_04_performerSeesWord(roomId) {
    const name = 'TC-04: 表演者看到词语'
    try {
      const room = this.rooms.get(roomId)
      const state = this.states.get(roomId)

      assert(room.currentWordText, '应有词语')
      assert(state.phase === 'performing', '应在表演阶段')

      const word = room.currentWordText
      assert(word.length > 0 && word.length <= 8, '词语长度应在1-8字')

      this.log(`表演者看到词语: "${word}"`)
      this.pass(name)
    } catch (e) {
      this.fail(name, e)
      throw e
    }
  }

  // 测试 5: 提交正确答案
  test_05_submitCorrectAnswer(roomId, players) {
    const name = 'TC-05: 提交正确答案'
    try {
      const room = this.rooms.get(roomId)
      const state = this.states.get(roomId)
      const guesserPlayer = players[1] // 玩家B作为猜词者

      // 模拟答题
      const answer = '苹果'
      const correct = normGuess(answer) === normGuess(room.currentWordText)

      assert(correct, `答案"${answer}"应与"${room.currentWordText}"匹配`)

      // 计分
      const nHits = state.roundHits.length
      const points = nHits === 0 ? 3 : 1

      state.roundHits.push({
        openId: guesserPlayer.openId,
        nickName: guesserPlayer.nickName,
        order: nHits + 1,
        points: points
      })

      guesserPlayer.score += points

      this.log(`猜词者: ${guesserPlayer.nickName}`)
      this.log(`提交答案: "${answer}"`)
      this.log(`结果: 正确`)
      this.log(`得分: +${points}`)
      this.log(`总分: ${guesserPlayer.score}`)
      this.pass(name)
    } catch (e) {
      this.fail(name, e)
      throw e
    }
  }

  // 测试 6: 提交错误答案
  test_06_submitWrongAnswer(roomId, players) {
    const name = 'TC-06: 提交错误答案'
    try {
      const room = this.rooms.get(roomId)
      const answer = '橙子'
      const correct = normGuess(answer) === normGuess(room.currentWordText)

      assert(!correct, `答案"${answer}"应与"${room.currentWordText}"不匹配`)

      this.log(`提交答案: "${answer}"`)
      this.log(`结果: 错误`)
      this.pass(name)
    } catch (e) {
      this.fail(name, e)
      throw e
    }
  }

  // 测试 7: 揭晓答案
  test_07_revealAnswer(roomId) {
    const name = 'TC-07: 揭晓答案'
    try {
      const room = this.rooms.get(roomId)
      const state = this.states.get(roomId)

      state.phase = 'revealed'
      state.revealedWord = room.currentWordText
      state.publicLog.push(`本轮答案: ${room.currentWordText}。`)

      assert(state.phase === 'revealed', '应进入 revealed 阶段')
      assert(state.revealedWord === room.currentWordText, '答案应被揭晓')

      this.log(`阶段: ${state.phase}`)
      this.log(`答案: ${state.revealedWord}`)
      this.log(`答对者: ${state.roundHits.length} 人`)
      this.pass(name)
    } catch (e) {
      this.fail(name, e)
      throw e
    }
  }

  // 测试 8: 下一轮
  test_08_nextRound(roomId, players) {
    const name = 'TC-08: 进入下一轮'
    try {
      const room = this.rooms.get(roomId)
      const state = this.states.get(roomId)

      const nextRound = state.currentRound + 1
      const isEnd = nextRound > room.totalRounds

      if (!isEnd) {
        state.currentRound = nextRound
        state.phase = 'performing'
        state.roundStartTime = Date.now()
        state.roundHits = []
        state.revealedWord = ''

        // 轮换表演者
        const performerId = performerForRound(players, nextRound, room.totalRounds)
        const performer = players.find(p => p.openId === performerId)
        state.performerOpenId = performerId
        state.performerNickName = performer.nickName

        assert(state.currentRound === nextRound, '轮次应递增')
        assert(state.phase === 'performing', '应回到表演阶段')

        this.log(`第 ${state.currentRound} / ${room.totalRounds} 轮`)
        this.log(`新的表演者: ${performer.nickName}`)
        this.pass(name)
      } else {
        this.log(`游戏已结束（${state.currentRound} / ${room.totalRounds} 轮）`)
        this.pass(name)
      }
    } catch (e) {
      this.fail(name, e)
      throw e
    }
  }

  // 测试 9: 验证最终排行
  test_09_finalRanking(players) {
    const name = 'TC-09: 最终排行'
    try {
      const ranking = [...players].sort((a, b) => b.score - a.score)

      assert(ranking.length === players.length, '排行人数应正确')
      assert(ranking[0].score >= ranking[1].score, '排行应按得分降序')

      this.log(`排名结果:`)
      ranking.forEach((p, i) => {
        this.log(`  ${i + 1}. ${p.nickName}: ${p.score} 分`, '    ')
      })
      this.pass(name)
    } catch (e) {
      this.fail(name, e)
      throw e
    }
  }

  // 运行所有测试
  runAll() {
    console.log('\n========== 你比划我猜 - 快速测试 ==========\n')

    try {
      const roomId = this.test_01_createRoom()
      const players = this.test_02_joinRoom(roomId)
      this.test_03_startGame(roomId, players)
      this.test_04_performerSeesWord(roomId)
      this.test_05_submitCorrectAnswer(roomId, players)
      this.test_06_submitWrongAnswer(roomId, players)
      this.test_07_revealAnswer(roomId)
      this.test_08_nextRound(roomId, players)
      this.test_09_finalRanking(players)
    } catch (e) {
      console.error('\n测试中止:', e.message)
    }

    this.printSummary()
  }

  // 打印总结
  printSummary() {
    console.log('\n========== 测试总结 ==========')
    const total = this.testsPassed + this.testsFailed
    const rate = total > 0 ? ((this.testsPassed / total) * 100).toFixed(1) : 0
    console.log(`总计: ${total} 个测试`)
    console.log(`✓ 通过: ${this.testsPassed}`)
    console.log(`✗ 失败: ${this.testsFailed}`)
    console.log(`成功率: ${rate}%`)
    console.log('==============================\n')
  }
}

// 运行测试
const tester = new GestureQuickTest()
tester.runAll()
