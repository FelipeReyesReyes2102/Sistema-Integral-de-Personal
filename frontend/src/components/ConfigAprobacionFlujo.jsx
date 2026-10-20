import { useEffect, useState } from 'react'
import { MessageSquareMore, RefreshCw, Save } from 'lucide-react'
import { api } from '../api'
import { fmtFecha } from '../utils'

const ESTADOS = { pendiente: 'En cola', enviada: 'Esperando respuesta', resuelta: 'Resueltas en Teams', cerrada: 'Resueltas en SIP-O', error: 'Con error' }

/** Aprobación en Teams con un flujo de Power Automate que SIP-O llama por HTTP (un solo flujo para toda la sede). */
export default function ConfigAprobacionFlujo({ sedeId }) {
  const [d, setD] = useState(null)
  const [form, setForm] = useState(null)
  const [msg, setMsg] = useState(null)
  const [ocupado, setOcupado] = useState(false)

  const aplicar = (r) => {
    setD(r)
    setForm({ activo: r.activo, tipos: r.tipos, flujo_url: '', lista_url: r.lista_url || '', cuenta_flujo: r.cuenta_flujo || '' })
  }
  useEffect(() => { api('/aprobacion-flujo', { sede: sedeId }).then(aplicar).catch((e) => setMsg({ ok: false, t: e.message })) }, [sedeId])
  if (!d || !form) return <div className="card">{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const toggleTipo = (t) => setForm({ ...form, tipos: form.tipos.includes(t) ? form.tipos.filter((x) => x !== t) : [...form.tipos, t] })

  async function correr(fn, ok) {
    setOcupado(true)
    setMsg(null)
    try {
      aplicar(await fn())
      setMsg({ ok: true, t: ok })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado(false)
    }
  }
  const guardar = () => correr(() => api('/aprobacion-flujo', { sede: sedeId, method: 'PUT', body: { ...form, flujo_url: form.flujo_url || null } }),
    form.activo ? 'Guardado. Las solicitudes nuevas se enviarán a Teams para su aprobación.' : 'Guardado (aprobación en Teams desactivada).')

  return (
    <div className="card">
      <h3 className="fila" style={{ gap: 8, marginBottom: 6 }}><MessageSquareMore size={18} /> Aprobación en Teams · {d.sede_nombre}</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Al enviarse una solicitud, SIP-O llama a un flujo de Power Automate (disparador <b>«Cuando se recibe una solicitud HTTP»</b>)
        que pide la aprobación al jefe en Teams y Outlook. El flujo deja la respuesta en la lista <b>Decisiones SIP-O</b> y SIP-O la
        aplica en menos de un minuto. También se puede seguir aprobando desde SIP-O.
      </p>
      <div className="pol-grid">
        <label className="campo full">URL del flujo (HTTP POST)
          <input type="password" autoComplete="off" value={form.flujo_url} onChange={set('flujo_url')}
            placeholder={d.configurado ? 'Configurada · pega otra solo para reemplazarla' : 'https://…logic.azure.com/workflows/…/invoke?…&sig=…'} />
          <span className="muted" style={{ fontSize: 11 }}>Se guarda cifrada y no se vuelve a mostrar: quien la tenga puede iniciar aprobaciones.</span>
        </label>
        <label className="campo full">Lista de decisiones (SharePoint)
          <input value={form.lista_url} onChange={set('lista_url')} placeholder="https://<empresa>.sharepoint.com/sites/<sitio>/Lists/Decisiones SIP-O" />
          {d.lista_nombre && <span className="muted" style={{ fontSize: 11 }}>Conectada: {d.lista_nombre}</span>}
        </label>
        <label className="campo">Cuenta con la que corre el flujo
          <input type="email" value={form.cuenta_flujo} onChange={set('cuenta_flujo')} placeholder="ti.mexico@o-tek.com" />
          <span className="muted" style={{ fontSize: 11 }}>Solo se aceptan decisiones registradas por esa cuenta.</span>
        </label>
        <div className="campo">
          <span>Qué se aprueba en Teams</span>
          <label className="checkbox"><input type="checkbox" checked={form.tipos.includes('vacaciones')} onChange={() => toggleTipo('vacaciones')} /> Vacaciones</label>
          <label className="checkbox"><input type="checkbox" checked={form.tipos.includes('permisos')} onChange={() => toggleTipo('permisos')} /> Permisos y home office</label>
        </div>
      </div>
      <div className="fila" style={{ marginTop: 10, gap: 8, flexWrap: 'wrap' }}>
        <label className="checkbox"><input type="checkbox" checked={form.activo} onChange={set('activo')} /> Enviar las aprobaciones a Teams</label>
        <div className="espacio" />
        {d.cuentas.error > 0 && <button className="btn btn-sm" disabled={ocupado} onClick={() => correr(() => api('/aprobacion-flujo/reintentar', { sede: sedeId, method: 'POST' }), 'Reintentando…')}><RefreshCw size={14} /> Reintentar</button>}
        <button className="btn btn-primary btn-sm" disabled={ocupado} onClick={guardar}><Save size={14} /> Guardar</button>
      </div>
      <div className="sp-info">
        {Object.entries(ESTADOS).map(([k, t]) => d.cuentas[k] > 0 && <span key={k} className={`sp-cuenta ${k === 'error' ? 'error' : k === 'resuelta' ? 'ok' : ''}`}>{d.cuentas[k]} {t.toLowerCase()}</span>)}
      </div>
      {d.avisos.length > 0 && (
        <div className="sp-errores">
          <b>Avisos recientes</b>
          {d.avisos.map((a) => <div key={a.folio} className="sp-error"><b>{a.folio}</b> · {fmtFecha(a.fecha)}<div>{a.texto}</div></div>)}
        </div>
      )}
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
    </div>
  )
}
