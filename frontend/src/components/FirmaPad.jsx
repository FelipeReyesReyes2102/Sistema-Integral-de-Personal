import { useEffect, useRef } from 'react'
import { Eraser } from 'lucide-react'

/** Área de firma con mouse, lápiz o dedo. Devuelve la firma como PNG (data URL) o null si se borra. */
export default function FirmaPad({ onChange }) {
  const canvasRef = useRef(null)
  const dibujando = useRef(false)
  const trazos = useRef(0)

  useEffect(() => {
    const canvas = canvasRef.current
    const ajustar = () => {
      const ratio = window.devicePixelRatio || 1
      const { width, height } = canvas.getBoundingClientRect()
      canvas.width = width * ratio
      canvas.height = height * ratio
      const ctx = canvas.getContext('2d')
      ctx.scale(ratio, ratio)
      ctx.lineWidth = 2.2
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.strokeStyle = '#13235b'
      trazos.current = 0
      onChange(null)
    }
    ajustar()
    window.addEventListener('resize', ajustar)
    return () => window.removeEventListener('resize', ajustar)
  }, [])

  const punto = (e) => {
    const r = canvasRef.current.getBoundingClientRect()
    return [e.clientX - r.left, e.clientY - r.top]
  }

  function inicio(e) {
    e.preventDefault()
    try { canvasRef.current.setPointerCapture(e.pointerId) } catch { /* puntero sin captura */ }
    dibujando.current = true
    const ctx = canvasRef.current.getContext('2d')
    const [x, y] = punto(e)
    ctx.beginPath()
    ctx.moveTo(x, y)
    ctx.lineTo(x + 0.1, y + 0.1)
    ctx.stroke()
  }

  function mover(e) {
    if (!dibujando.current) return
    const ctx = canvasRef.current.getContext('2d')
    const [x, y] = punto(e)
    ctx.lineTo(x, y)
    ctx.stroke()
    trazos.current += 1
  }

  function fin() {
    if (!dibujando.current) return
    dibujando.current = false
    if (trazos.current > 3) onChange(canvasRef.current.toDataURL('image/png'))
  }

  function borrar() {
    const c = canvasRef.current
    c.getContext('2d').clearRect(0, 0, c.width, c.height)
    trazos.current = 0
    onChange(null)
  }

  return (
    <div className="firma">
      <button type="button" className="firma-borrar" onClick={borrar} title="Borrar firma"><Eraser size={30} /></button>
      <canvas ref={canvasRef} className="firma-area" onPointerDown={inicio} onPointerMove={mover}
        onPointerUp={fin} onPointerLeave={fin} aria-label="Área para firmar" />
    </div>
  )
}
