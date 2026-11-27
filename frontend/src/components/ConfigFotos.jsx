import { useEffect, useState } from 'react'
import { ExternalLink, Image, Link2, Unplug, UploadCloud } from 'lucide-react'
import { api } from '../api'

/** Super administrador: biblioteca de SharePoint donde se guardan las fotos de los empleados. */
export default function ConfigFotos() {
  const [d, setD] = useState(null)
  const [url, setUrl] = useState('')
  const [carpeta, setCarpeta] = useState('')
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')
  const [ocupado, setOcupado] = useState('')

  useEffect(() => {
    api('/fotos-sharepoint').then((r) => { setD(r); setUrl(r.url || '') }).catch((e) => setError(e.message))
  }, [])

  async function ejecutar(clave, fn, mensaje) {
    setOcupado(clave); setError(''); setAviso('')
    try {
      const r = await fn()
      setD(r)
      setAviso(typeof mensaje === 'function' ? mensaje(r) : mensaje)
    } catch (e) { setError(e.message) } finally { setOcupado('') }
  }

  if (!d) return <div className="card">{error ? <div className="alerta error">{error}</div> : 'Cargando…'}</div>
  const conectar = () => ejecutar('conectar', () => api('/fotos-sharepoint/conectar', { method: 'PUT', body: { url, carpeta: carpeta || null } }),
    (r) => `Biblioteca conectada: ${r.drive_nombre} / ${r.carpeta}.`)
  const activar = (activo) => ejecutar('activo', () => api('/fotos-sharepoint/activo', { method: 'PUT', body: { activo } }),
    activo ? 'Las fotos nuevas se guardarán en SharePoint.' : 'Pausado: las fotos nuevas se guardan en el servidor.')
  const mover = () => {
    if (!window.confirm(`Se subirán ${d.en_servidor} fotos a SharePoint. Cada foto se borra del servidor solo cuando SharePoint confirma que la recibió completa. ¿Continuar?`)) return
    ejecutar('mover', () => api('/fotos-sharepoint/mover', { method: 'POST' }),
      (r) => `${r.movidas} fotos movidas a SharePoint.${r.pendientes ? ` ${r.pendientes} siguen en el servidor.` : ''}${r.errores?.length ? ' Errores: ' + r.errores.join(' · ') : ''}`)
  }
  const desconectar = () => {
    if (!window.confirm('Las fotos nuevas volverán a guardarse en el servidor. Las que ya están en SharePoint se seguirán leyendo de ahí. ¿Desconectar?')) return
    ejecutar('desconectar', () => api('/fotos-sharepoint', { method: 'DELETE' }), 'Biblioteca desconectada.')
  }

  return (
    <div className="card">
      <h3 className="fila" style={{ gap: 8, marginBottom: 6 }}><Image size={18} /> Fotos de los empleados en SharePoint</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Las fotos se guardan en una biblioteca de documentos de SharePoint como «nómina - nombre.jpg» y el servidor solo
        conserva la referencia. Para mostrarlas en SIP-O (caseta, perfil y tarjetas), el servidor las lee de SharePoint.
        Si Microsoft no responde al guardar una foto, se queda en el servidor hasta moverla. Quitar una foto la envía a la
        papelera de reciclaje del sitio. Requiere el permiso de aplicación <b>Sites.ReadWrite.All</b> (o Sites.Selected con
        escritura en el sitio).
      </p>

      <div className="fila" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label className="campo" style={{ flex: '1 1 380px' }}>URL de la biblioteca o de una carpeta
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://empresa.sharepoint.com/sites/GH/Documentos compartidos/..." />
        </label>
        <label className="campo" style={{ flex: '0 1 220px' }}>Carpeta (opcional)
          <input value={carpeta} onChange={(e) => setCarpeta(e.target.value)} placeholder={d.carpeta || 'Fotos SIP-O'} />
        </label>
        <button className="btn btn-primary" onClick={conectar} disabled={!url.trim() || !!ocupado}>
          <Link2 size={16} /> {ocupado === 'conectar' ? 'Conectando…' : d.conectada ? 'Volver a conectar' : 'Conectar'}
        </button>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
        Abre en SharePoint la biblioteca (o la carpeta) y copia la dirección del navegador. Si no indicas carpeta y la URL es
        de la biblioteca, se crea «Fotos SIP-O».
      </p>

      {d.conectada && (
        <div className="card" style={{ marginTop: 14, background: 'var(--fondo-suave, #f6f8fb)' }}>
          <div className="fila" style={{ gap: 8, flexWrap: 'wrap', justifyContent: 'space-between' }}>
            <div>
              <b>{d.sitio_nombre}</b> · {d.drive_nombre} / {d.carpeta}
              {d.web_url && <a href={d.web_url} target="_blank" rel="noreferrer" style={{ marginLeft: 8, fontSize: 13 }}>Abrir <ExternalLink size={12} /></a>}
              <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                {d.en_sharepoint} fotos en SharePoint · {d.en_servidor} en el servidor
              </div>
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={d.activo} disabled={!!ocupado} onChange={(e) => activar(e.target.checked)} />
              Guardar las fotos nuevas en SharePoint
            </label>
          </div>
          <div className="fila" style={{ gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            <button className="btn" onClick={mover} disabled={!d.activo || !d.en_servidor || !!ocupado}
              title={d.activo ? '' : 'Activa primero «Guardar las fotos nuevas en SharePoint»'}>
              <UploadCloud size={16} /> {ocupado === 'mover' ? 'Moviendo…' : `Mover a SharePoint las ${d.en_servidor} fotos del servidor`}
            </button>
            <button className="btn" onClick={desconectar} disabled={!!ocupado}><Unplug size={16} /> Desconectar</button>
          </div>
          {d.en_servidor > 0 && d.activo && (
            <p className="muted" style={{ fontSize: 12, margin: '8px 0 0' }}>
              Antes de mover las fotos existentes, conviene tener un respaldo reciente de la base de datos.
            </p>
          )}
        </div>
      )}
      {aviso && <div className="alerta ok" style={{ marginTop: 10 }}>{aviso}</div>}
      {error && <div className="alerta error" style={{ marginTop: 10 }}>{error}</div>}
    </div>
  )
}
