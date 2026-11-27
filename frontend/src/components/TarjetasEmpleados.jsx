import { useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'
import { Printer } from 'lucide-react'
import { api } from '../api'
import Modal from './Modal'

const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const iniciales = (n) => (n || '?').split(' ').filter(Boolean).map((x) => x[0]).slice(0, 2).join('').toUpperCase()

/** Tarjeta vertical tamaño credencial (CR80: 54 × 85.6 mm) con foto, datos y QR para caseta. */
function tarjetaHtml(t, qr, op, origen) {
  const foto = t.tiene_foto
    ? `<img class="foto" src="${origen}/api/usuarios/${t.id}/foto" alt="">`
    : `<div class="foto sin">${esc(iniciales(t.nombre))}</div>`
  return `<div class="t">
    <div class="cab"><span class="logo"><img src="${origen}/logo-otek.png" alt="O-tek"></span><span class="sis">SIP-O</span></div>
    ${foto}
    <div class="nom">${esc(t.nombre)}</div>
    ${op.puesto && t.puesto ? `<div class="pue">${esc(t.puesto)}</div>` : ''}
    ${op.departamento && t.departamento ? `<div class="dep">${esc(t.departamento)}</div>` : ''}
    <img class="qr" src="${qr}" alt="QR">
    <div class="pie">${[op.numero && t.numero_empleado ? `No. ${esc(t.numero_empleado)}` : '', esc(t.sede_nombre || '')].filter(Boolean).join(' · ')}</div>
  </div>`
}

const CSS = `
*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.hoja{display:grid;grid-template-columns:repeat(3,54mm);gap:5mm;justify-content:center;padding:0}
.t{width:54mm;height:85.6mm;border:.2mm dashed #b8c0cc;border-radius:3mm;overflow:hidden;display:flex;flex-direction:column;align-items:center;
  background:#fff;break-inside:avoid;page-break-inside:avoid;position:relative}
.cab{width:100%;height:12mm;background:#1b2a4a;display:flex;align-items:center;justify-content:space-between;padding:0 3mm}
.logo{background:#fff;border-radius:1.5mm;padding:.8mm 1.5mm;display:flex}.logo img{height:6mm;display:block}
.sis{color:#fff;font-weight:700;font-size:10pt;letter-spacing:.5pt}
.foto{width:24mm;height:24mm;border-radius:50%;object-fit:cover;margin-top:3mm;border:.8mm solid #1b2a4a;background:#e9edf3}
.foto.sin{display:flex;align-items:center;justify-content:center;font-size:16pt;font-weight:700;color:#1b2a4a}
.nom{font-weight:700;font-size:9.5pt;line-height:1.15;text-align:center;padding:0 3mm;margin-top:2mm;max-height:8.6mm;overflow:hidden}
.pue{font-size:7.5pt;color:#333;text-align:center;padding:0 3mm;margin-top:.8mm;line-height:1.15;max-height:5.4mm;overflow:hidden}
.dep{font-size:7pt;color:#667;text-align:center;padding:0 3mm;margin-top:.4mm;line-height:1.15;max-height:5mm;overflow:hidden}
.qr{width:26mm;height:26mm;margin-top:auto}
.pie{width:100%;font-size:6.5pt;color:#fff;background:#1b2a4a;text-align:center;padding:1.2mm 2mm;margin-top:1.5mm;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media print{.t{border-color:#d0d5dd}}
`

function documento(tarjetas, qrs, op, origen) {
  const pvc = op.formato === 'cr80'
  const pagina = pvc ? '@page{size:54mm 85.6mm;margin:0}.hoja{display:block}.t{border:0;border-radius:0;page-break-after:always}'
    : '@page{size:letter;margin:10mm}'
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Tarjetas de empleados</title>
    <style>${CSS}${pagina}</style></head><body><div class="hoja">
    ${tarjetas.map((t) => tarjetaHtml(t, qrs[t.id], op, origen)).join('')}
    </div></body></html>`
}

/** GH imprime las tarjetas (gafetes) de los empleados con su foto, sus datos y su QR para caseta. */
export default function TarjetasEmpleados({ seleccionados, lista, onClose }) {
  const [quienes, setQuienes] = useState(seleccionados.length ? 'sel' : 'lista')
  const [op, setOp] = useState({ numero: true, puesto: true, departamento: true, formato: 'carta' })
  const [datos, setDatos] = useState(null)
  const [qrs, setQrs] = useState({})
  const [error, setError] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const ids = useMemo(() => (quienes === 'sel' ? seleccionados : lista).filter((u) => u.activo).map((u) => u.id), [quienes, seleccionados, lista])
  const origen = window.location.origin

  useEffect(() => {
    if (!ids.length) { setDatos([]); return }
    let vigente = true
    setError('')
    setDatos(null)
    api('/caseta/tarjetas', { method: 'POST', body: { ids } })
      .then(async (d) => {
        const q = {}
        for (const t of d) q[t.id] = await QRCode.toDataURL(t.codigo, { width: 400, margin: 1, errorCorrectionLevel: 'M' })
        if (vigente) { setQrs(q); setDatos(d) }
      })
      .catch((e) => vigente && setError(e.message))
    return () => { vigente = false }
  }, [ids])

  function imprimir() {
    const w = window.open('', '_blank')
    if (!w) { setError('El navegador bloqueó la ventana de impresión; permite las ventanas emergentes de SIP-O.'); return }
    setOcupado(true)
    w.document.write(documento(datos, qrs, op, origen))
    w.document.close()
    // Imprime cuando cargaron las fotos y los logos
    const listo = () => Promise.all([...w.document.images].map((i) => (i.complete ? null : new Promise((r) => { i.onload = r; i.onerror = r }))))
    listo().then(() => { w.focus(); w.print(); setOcupado(false) })
  }

  const set = (k) => (e) => setOp({ ...op, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const sinQr = (datos || []).filter((t) => !t.qr_activo).length
  const muestra = datos?.[0]
  return (
    <Modal titulo="Imprimir tarjetas de empleados" onClose={onClose} ancho
      pie={<>
        <button className="btn" onClick={onClose}>Cerrar</button>
        <button className="btn btn-primary" onClick={imprimir} disabled={!datos?.length || ocupado}>
          <Printer size={16} /> Imprimir {datos ? datos.length : ''} tarjeta{datos?.length === 1 ? '' : 's'}
        </button>
      </>}>
      <div className="tarjetas-config">
        <div>
          <div className="campo">
            <span>Empleados</span>
            <label className="checkbox"><input type="radio" name="quienes" checked={quienes === 'sel'} disabled={!seleccionados.length}
              onChange={() => setQuienes('sel')} /> Los seleccionados en la lista ({seleccionados.length})</label>
            <label className="checkbox"><input type="radio" name="quienes" checked={quienes === 'lista'} onChange={() => setQuienes('lista')} />
              Todos los activos de la lista ({lista.filter((u) => u.activo).length}) <span className="muted" style={{ fontSize: 12 }}>· usa los filtros y la búsqueda</span></label>
          </div>
          <div className="campo" style={{ marginTop: 10 }}>
            <span>Datos en la tarjeta</span>
            <label className="checkbox"><input type="checkbox" checked disabled /> Foto, nombre completo, QR y sede</label>
            <label className="checkbox"><input type="checkbox" checked={op.numero} onChange={set('numero')} /> Número de nómina</label>
            <label className="checkbox"><input type="checkbox" checked={op.puesto} onChange={set('puesto')} /> Puesto</label>
            <label className="checkbox"><input type="checkbox" checked={op.departamento} onChange={set('departamento')} /> Departamento</label>
          </div>
          <label className="campo" style={{ marginTop: 10 }}>Formato
            <select value={op.formato} onChange={set('formato')}>
              <option value="carta">Hoja carta: 9 tarjetas por hoja, con línea de corte</option>
              <option value="cr80">Impresora de credenciales (PVC CR80): una por tarjeta</option>
            </select>
          </label>
          <p className="muted" style={{ fontSize: 12 }}>Tamaño credencial: 5.4 × 8.6 cm. Al imprimir, elige escala 100 % («Tamaño real») y activa «Gráficos de fondo».</p>
          {sinQr > 0 && <div className="alerta warn" style={{ fontSize: 12 }}>{sinQr === datos.length ? 'La sede' : `${sinQr} de estas personas son de una sede que`} aún no usa el registro con QR en caseta. Puedes imprimir las tarjetas ya; el QR funcionará cuando GH lo active en Configuración → Política.</div>}
          {error && <div className="alerta error">{error}</div>}
        </div>
        <div className="tarjetas-muestra">
          <span className="muted" style={{ fontSize: 12 }}>Vista previa{muestra ? ` · ${muestra.nombre}` : ''}</span>
          {!datos && !error && ids.length > 0 && <div className="muted" style={{ padding: 20 }}>Preparando…</div>}
          {datos && !datos.length && <div className="muted" style={{ padding: 20 }}>No hay empleados activos para imprimir.</div>}
          {muestra && <iframe title="Vista previa de la tarjeta" sandbox="allow-same-origin"
            srcDoc={`<!doctype html><html><head><meta charset="utf-8"><style>${CSS}body{display:flex;justify-content:center;padding:8px;background:#f3f5f8}.t{zoom:1.15}</style></head><body>${tarjetaHtml(muestra, qrs[muestra.id], op, origen)}</body></html>`} />}
        </div>
      </div>
    </Modal>
  )
}
