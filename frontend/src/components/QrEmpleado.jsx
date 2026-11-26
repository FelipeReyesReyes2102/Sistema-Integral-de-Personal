import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { Printer } from 'lucide-react'
import { api } from '../api'

/** QR del empleado para registrar sus entradas y salidas en caseta (propio, o el de otro empleado para GH). */
export default function QrEmpleado({ usuarioId, tam = 180 }) {
  const [datos, setDatos] = useState(null)
  const [img, setImg] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    api(usuarioId ? `/caseta/qr/${usuarioId}` : '/caseta/qr/mio')
      .then(async (d) => {
        setDatos(d)
        setImg(await QRCode.toDataURL(d.codigo, { width: 480, margin: 1, errorCorrectionLevel: 'M' }))
      })
      .catch((e) => setError(e.message))
  }, [usuarioId])

  function imprimir() {
    const w = window.open('', '_blank', 'width=420,height=560')
    if (!w) return
    const esc = (t) => String(t || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
    w.document.write(`<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Gafete ${esc(datos.nombre)}</title>
      <style>body{font-family:Arial,sans-serif;text-align:center;margin:24px}.g{display:inline-block;border:1px solid #ccc;border-radius:10px;padding:16px 20px}
      img{width:220px;height:220px}h2{margin:8px 0 2px;font-size:18px}p{margin:0;color:#555;font-size:13px}</style></head>
      <body><div class="g"><b style="color:#1f4a86">SIP-O · Caseta</b><br><img src="${img}" alt="QR"><h2>${esc(datos.nombre)}</h2><p>No. ${esc(datos.numero_empleado)}</p></div>
      <script>window.onload=function(){window.print()}</script></body></html>`)
    w.document.close()
  }

  if (error) return <div className="muted" style={{ fontSize: 12 }}>{error}</div>
  if (!img) return <div className="muted" style={{ fontSize: 12 }}>Cargando QR…</div>
  return (
    <div className="qr-empleado">
      <img src={img} alt={`QR de ${datos.nombre} para caseta`} width={tam} height={tam} />
      <button type="button" className="btn btn-sm" onClick={imprimir}><Printer size={14} /> Imprimir gafete</button>
    </div>
  )
}
