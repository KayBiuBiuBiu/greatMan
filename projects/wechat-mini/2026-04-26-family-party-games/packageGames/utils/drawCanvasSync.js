/**
 * 你画我猜 · 画板笔画绘制与重放（画家/观看端统一尺寸）
 */
const DRAW_CANVAS_W = 280
const DRAW_CANVAS_H = 400

function drawStrokeOnCtx (ctx, stroke, bounds) {
  if (!ctx || !stroke) {
    return
  }
  const pts = stroke.pts || []
  if (pts.length < 2) {
    return
  }
  const w = (bounds && bounds.w) || 280
  const h = (bounds && bounds.h) || 400
  ctx.strokeStyle = stroke.c || '#111111'
  ctx.lineWidth = stroke.w | 0 || 4
  if (ctx.setLineCap) {
    ctx.setLineCap('round')
  }
  if (ctx.setLineJoin) {
    ctx.setLineJoin('round')
  }
  if (ctx.beginPath) {
    ctx.beginPath()
  }
  const p0 = clampPt(pts[0][0], pts[0][1], w, h)
  if (ctx.moveTo) {
    ctx.moveTo(p0[0], p0[1])
  }
  for (let i = 1; i < pts.length; i += 1) {
    const p = clampPt(pts[i][0], pts[i][1], w, h)
    if (ctx.lineTo) {
      ctx.lineTo(p[0], p[1])
    }
  }
  if (ctx.stroke) {
    ctx.stroke()
  }
}

function clampPt (x, y, w, h) {
  const nx = Number(x)
  const ny = Number(y)
  return [
    Math.max(0, Math.min(w, isNaN(nx) ? 0 : nx)),
    Math.max(0, Math.min(h, isNaN(ny) ? 0 : ny))
  ]
}

/** 公屏 canvasData：云库可能是 JSON 字符串或数组 */
function parseCanvasData (raw) {
  if (Array.isArray(raw)) {
    return raw
  }
  if (typeof raw === 'string') {
    const s = raw.trim()
    if (!s) {
      return []
    }
    try {
      const parsed = JSON.parse(s)
      return Array.isArray(parsed) ? parsed : []
    } catch (e) {
      return []
    }
  }
  return []
}

function normalizeStrokeInput (stroke, color, lineW) {
  const pts = (stroke && stroke.pts) || []
  const out = []
  for (let i = 0; i < pts.length && out.length < 64; i += 1) {
    const p = pts[i]
    if (!p || p.length < 2) {
      continue
    }
    out.push([Math.round(p[0] | 0), Math.round(p[1] | 0)])
  }
  if (out.length < 2) {
    return null
  }
  return {
    c: String((stroke && stroke.c) || color || '#111111').slice(0, 16),
    w: Math.min(20, Math.max(1, ((stroke && stroke.w) | 0) || (lineW | 0) || 4)),
    pts: out
  }
}

module.exports = {
  DRAW_CANVAS_W,
  DRAW_CANVAS_H,
  drawStrokeOnCtx,
  clampPt,
  parseCanvasData,
  normalizeStrokeInput
}
