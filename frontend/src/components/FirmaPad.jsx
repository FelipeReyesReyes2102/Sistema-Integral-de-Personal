import { useEffect, useRef } from 'react'
import { Eraser } from 'lucide-react'

const COLOR = '#13235b'
const MIN = 0.9   // grosor mínimo (trazo rápido)
const MAX = 3.0   // grosor máximo (trazo lento o con presión)
const ESCALA_EXPORT = 3 // la imagen guardada se genera a 3× para que no se vea pixelada

/** Grosor según la velocidad (y la presión del lápiz, si la hay), suavizado para que no "salte". */
function grosor(prev, p) {
  if (!prev) return (MIN + MAX) / 2
  const dt = Math.max(p.t - prev.t, 1)
  const v = Math.hypot(p.x - prev.x, p.y - prev.y) / dt // px por ms
  let w = Math.max(MIN, Math.min(MAX, MAX - v * 1.6))
  if (p.presion > 0 && p.presion !== 0.5) w = MIN + (MAX - MIN) * p.presion // lápiz con presión real
  return prev.w * 0.6 + w * 0.4
}

/** Dibuja un trazo con curvas entre los puntos medios y grosor variable. */
function dibujarTrazo(ctx, pts, desde = 1) {
  ctx.fillStyle = COLOR
  ctx.strokeStyle = COLOR
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  if (pts.length === 1) {
    ctx.beginPath()
    ctx.arc(pts[0].x, pts[0].y, pts[0].w / 2, 0, Math.PI * 2)
    ctx.fill()
    return
  }
  for (let i = Math.max(desde, 1); i < pts.length; i++) {
    const a = pts[i - 2] || pts[i - 1]
    const b = pts[i - 1]
    const c = pts[i]
    const ini = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
    const fin = { x: (b.x + c.x) / 2, y: (b.y + c.y) / 2 }
    ctx.beginPath()
    ctx.lineWidth = (b.w + c.w) / 2
    ctx.moveTo(i === 1 ? b.x : ini.x, i === 1 ? b.y : ini.y)
    ctx.quadraticCurveTo(b.x, b.y, fin.x, fin.y)
    ctx.stroke()
  }
}

/** Área de firma con mouse, lápiz o dedo. Devuelve la firma como PNG (data URL) o null si se borra. */
export default function FirmaPad({ onChange }) {
  const canvasRef = useRef(null)
  const trazos = useRef([])      // [[{x, y, t, w, presion}]] para redibujar y exportar en alta resolución
  const actual = useRef(null)

  const redibujar = () => {
    const c = canvasRef.current
    const ratio = window.devicePixelRatio || 1
    const ctx = c.getContext('2d')
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    ctx.clearRect(0, 0, c.width, c.height)
    trazos.current.forEach((t) => dibujarTrazo(ctx, t))
  }

  useEffect(() => {
    const canvas = canvasRef.current
    const ajustar = () => {
      const ratio = window.devicePixelRatio || 1
      const { width, height } = canvas.getBoundingClientRect()
      canvas.width = Math.round(width * ratio)
      canvas.height = Math.round(height * ratio)
      redibujar() // al cambiar el tamaño de la ventana la firma se conserva
    }
    ajustar()
    onChange(null)
    window.addEventListener('resize', ajustar)
    return () => window.removeEventListener('resize', ajustar)
  }, [])

  const punto = (e, prev) => {
    const r = canvasRef.current.getBoundingClientRect()
    const p = { x: e.clientX - r.left, y: e.clientY - r.top, t: e.timeStamp || performance.now(),
      presion: e.pointerType === 'pen' ? e.pressure : 0 }
    p.w = grosor(prev, p)
    return p
  }

  function inicio(e) {
    e.preventDefault()
    try { canvasRef.current.setPointerCapture(e.pointerId) } catch { /* puntero sin captura */ }
    const pts = [punto(e, null)]
    actual.current = pts
    trazos.current.push(pts)
    dibujarTrazo(canvasRef.current.getContext('2d'), pts)
  }

  function mover(e) {
    const pts = actual.current
    if (!pts) return
    const n = pts.length
    // Todos los puntos intermedios que captó el navegador (trazo más fino y continuo)
    const eventos = e.nativeEvent.getCoalescedEvents ? e.nativeEvent.getCoalescedEvents() : [e.nativeEvent]
    for (const ev of (eventos.length ? eventos : [e.nativeEvent])) {
      const p = punto(ev, pts[pts.length - 1])
      const ult = pts[pts.length - 1]
      if (Math.hypot(p.x - ult.x, p.y - ult.y) >= 0.8) pts.push(p)
    }
    if (pts.length > n) dibujarTrazo(canvasRef.current.getContext('2d'), pts, n)
  }

  function fin() {
    const pts = actual.current
    if (!pts) return
    actual.current = null
    // Remata el final del trazo hasta el último punto
    if (pts.length > 1) {
      const ctx = canvasRef.current.getContext('2d')
      const a = pts[pts.length - 2]
      const b = pts[pts.length - 1]
      ctx.beginPath()
      ctx.lineWidth = b.w
      ctx.moveTo((a.x + b.x) / 2, (a.y + b.y) / 2)
      ctx.lineTo(b.x, b.y)
      ctx.stroke()
      pts.push({ ...b }) // para que el redibujado incluya el remate
    }
    const total = trazos.current.reduce((s, t) => s + t.length, 0)
    if (total > 4) onChange(exportar())
  }

  /** PNG recortado al área firmada, a 3× de resolución y con fondo transparente. */
  function exportar() {
    const todos = trazos.current.flat()
    const margen = MAX * 2
    const minX = Math.max(0, Math.min(...todos.map((p) => p.x)) - margen)
    const minY = Math.max(0, Math.min(...todos.map((p) => p.y)) - margen)
    const maxX = Math.max(...todos.map((p) => p.x)) + margen
    const maxY = Math.max(...todos.map((p) => p.y)) + margen
    const c = document.createElement('canvas')
    c.width = Math.ceil((maxX - minX) * ESCALA_EXPORT)
    c.height = Math.ceil((maxY - minY) * ESCALA_EXPORT)
    const ctx = c.getContext('2d')
    ctx.setTransform(ESCALA_EXPORT, 0, 0, ESCALA_EXPORT, -minX * ESCALA_EXPORT, -minY * ESCALA_EXPORT)
    trazos.current.forEach((t) => dibujarTrazo(ctx, t))
    return c.toDataURL('image/png')
  }

  function borrar() {
    trazos.current = []
    actual.current = null
    redibujar()
    onChange(null)
  }

  return (
    <div className="firma">
      <canvas ref={canvasRef} className="firma-area" onPointerDown={inicio} onPointerMove={mover}
        onPointerUp={fin} onPointerCancel={fin} onPointerLeave={fin} aria-label="Área para firmar" />
      <button type="button" className="firma-borrar" onClick={borrar} title="Borrar firma"><Eraser size={14} /> Borrar</button>
    </div>
  )
}
