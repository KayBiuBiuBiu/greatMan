/**
 * AI 缓存键与 TTL（Node 单测）
 * 命令：node scripts/test-ai-cache.js
 */
const {
  buildAiCacheKey,
  clearAiCache,
  CACHE_TTL_MS,
  validateUndercoverPair,
  validateDrawWord,
  sanitizeDisplayText
} = require('../utils/aiHelper')

function assert(cond, msg) {
  if (!cond) {
    throw new Error(msg || 'assert failed')
  }
}

function t(name, fn) {
  try {
    fn()
    console.log('ok', name)
  } catch (e) {
    console.error('FAIL', name, e.message)
    process.exitCode = 1
  }
}

clearAiCache()

t('cache key includes tag room round', () => {
  const a = buildAiCacheKey({
    cacheTag: 'drink-comment',
    roomId: 'r1',
    round: '3',
    system: 'sys',
    prompt: 'hello'
  })
  const b = buildAiCacheKey({
    cacheTag: 'drink-task',
    roomId: 'r1',
    round: '3',
    system: 'sys',
    prompt: 'hello'
  })
  assert(a !== b, 'different tags must differ')
})

t('same key for same inputs', () => {
  const meta = {
    cacheTag: 'x',
    roomId: '1',
    round: '1',
    system: 's',
    prompt: 'p'
  }
  assert(buildAiCacheKey(meta) === buildAiCacheKey(meta))
})

// mock generateText path: inject cache manually via generateTextCached only works with real API
// test cache hit by calling setCache through two generateTextCached - skip network test

t('CACHE_TTL is 5 min', () => {
  assert(CACHE_TTL_MS === 5 * 60 * 1000)
})

t('validate undercover pair', () => {
  const v = validateUndercoverPair('{"civilianWord":"饺子","undercoverWord":"包子"}')
  assert(v.ok && v.civilianWord === '饺子')
})

t('validate draw word', () => {
  const v = validateDrawWord('{"word":"大象"}')
  assert(v.ok && v.word === '大象')
})

t('sanitize strips long', () => {
  const s = sanitizeDisplayText('一二三四五六七八九十', 5)
  assert(s.length <= 6)
})

if (process.exitCode) {
  process.exit(process.exitCode)
}
console.log('all ai-cache tests passed')
