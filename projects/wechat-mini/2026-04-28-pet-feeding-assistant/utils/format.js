function pad (n) {
  return n < 10 ? '0' + n : '' + n
}

function formatDate (ts) {
  if (!ts) {
    return '—'
  }
  const d = new Date(typeof ts === 'number' ? ts : Number(ts))
  if (isNaN(d.getTime())) {
    return '—'
  }
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
}

function formatDateTime (ts) {
  if (!ts) {
    return '—'
  }
  const d = new Date(typeof ts === 'number' ? ts : Number(ts))
  if (isNaN(d.getTime())) {
    return '—'
  }
  return (
    formatDate(ts) +
    ' ' +
    pad(d.getHours()) +
    ':' +
    pad(d.getMinutes())
  )
}

function startOfDay (d) {
  const x = new Date(d)
  x.setHours(0, 0, 0, 0)
  return x.getTime()
}

function endOfDay (d) {
  const x = new Date(d)
  x.setHours(23, 59, 59, 999)
  return x.getTime()
}

module.exports = {
  formatDate,
  formatDateTime,
  startOfDay,
  endOfDay
}
