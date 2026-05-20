const {
  SIZES,
  stepSizeIndex,
  indexOfSize,
  isValidSize
} = require('../utils/wolfBoardSize')

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

t('sizes', () => {
  assert(SIZES.join(',') === '6,8,10,12')
})

t('step up down', () => {
  assert(stepSizeIndex(0, 1).index === 1 && stepSizeIndex(0, 1).size === 8)
  assert(stepSizeIndex(3, 1).atBoundary === true)
  assert(stepSizeIndex(3, -1).index === 2)
  assert(stepSizeIndex(0, -1).atBoundary === true)
})

t('indexOfSize', () => {
  assert(indexOfSize(10) === 2)
  assert(isValidSize(12))
  assert(!isValidSize(7))
})

if (!process.exitCode) {
  console.log('all wolf-board-size tests passed')
}
