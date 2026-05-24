function randomInt(max) {
  if (max <= 0) return 0
  return Math.floor(Math.random() * max)
}

function pickOne(list) {
  if (!list || list.length === 0) return null
  return list[randomInt(list.length)]
}

function shuffle(list) {
  const copy = list.slice()
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = randomInt(i + 1)
    const temp = copy[i]
    copy[i] = copy[j]
    copy[j] = temp
  }
  return copy
}

function createPlayers(count) {
  return Array.from({ length: count }, function (_, index) {
    return {
      id: index + 1,
      name: '参与者' + (index + 1)
    }
  })
}

module.exports = {
  randomInt,
  pickOne,
  shuffle,
  createPlayers
}
