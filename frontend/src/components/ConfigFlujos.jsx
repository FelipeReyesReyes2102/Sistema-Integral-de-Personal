import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, GitBranch, Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import { api } from '../api'

const APROBADORES = {
  jefe: 'Jefe directo', jefe_del_jefe: 'Jefe del jefe', gh: 'GH de la sede', ti: 'TI', usuario: 'Persona específica',
}
const PASO_NUEVO = { aprobador: 'jefe', usuario_id: '', teams: true, si_falta: 'omitir' }

/** Cadenas de aprobación de la sede: pasos en orden que se asignan a cada tipo de permiso. */
export default function ConfigFlujos() {
  const [flujos, setFlujos] = useState(null)
  const [personas, setPersonas] = useState([])
  const [edicion, setEdicion] = useState(null)
  const [msg, setMsg] = useState(null)

  const cargar = () => api('/flujos').then(setFlujos).catch((e) => setMsg({ ok: false, t: e.message }))
  useEffect(() => {
    cargar()
    api('/usuarios', { query: { activos: true } }).then(setPersonas).catch(() => {})
  }, [])
  if (!flujos) return <div className="card">{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>

  const setPaso = (i, k) => (e) => {
    const valor = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setEdicion({ ...edicion, pasos: edicion.pasos.map((p, j) => (j === i ? { ...p, [k]: valor } : p)) })
  }
  const mover = (i, d) => {
    const pasos = [...edicion.pasos]
    ;[pasos[i], pasos[i + d]] = [pasos[i + d], pasos[i]]
    setEdicion({ ...edicion, pasos })
  }

  async function guardar() {
    setMsg(null)
    const body = {
      nombre: edicion.nombre.trim(), activo: edicion.activo,
      pasos: edicion.pasos.map((p) => ({ ...p, usuario_id: p.aprobador === 'usuario' && p.usuario_id ? Number(p.usuario_id) : null })),
    }
    try {
      if (edicion.id) await api(`/flujos/${edicion.id}`, { method: 'PUT', body })
      else await api('/flujos', { method: 'POST', body })
      setEdicion(null)
      setMsg({ ok: true, t: `Flujo "${body.nombre}" guardado. Aplica a los permisos que se envíen desde ahora.` })
      cargar()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  async function borrar(f) {
    if (!window.confirm(`¿Eliminar el flujo "${f.nombre}"?`)) return
    setMsg(null)
    try {
      await api(`/flujos/${f.id}`, { method: 'DELETE' })
      cargar()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  return (
    <div className="card">
      <h3 className="fila" style={{ gap: 8, marginBottom: 6 }}><GitBranch size={18} /> Flujos de aprobación</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Arma cadenas de aprobación (p. ej. <b>Jefe → TI → GH</b>) y asígnalas a cada tipo en <i>Tipos de permiso</i>. Al aprobar un
        paso se activa el siguiente; un rechazo termina la solicitud. En los pasos de GH o TI basta con que apruebe uno. GH siempre
        puede validar directamente. Los tipos sin flujo siguen la regla de la sede (jefe, o jefe y después GH).
      </p>
      {!edicion && (
        <div className="tabla-wrap">
          <table className="tabla">
            <thead><tr><th>Flujo</th><th>Pasos</th><th>Lo usan</th><th>Estado</th><th /></tr></thead>
            <tbody>
              {flujos.map((f) => (
                <tr key={f.id} style={{ opacity: f.activo ? 1 : 0.5 }}>
                  <td><b>{f.nombre}</b></td>
                  <td>{f.resumen}</td>
                  <td>{f.tipos.length ? f.tipos.join(', ') : <span className="muted">Ningún tipo</span>}</td>
                  <td>{f.activo ? 'Activo' : 'Inactivo'}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <button className="icon-btn" title="Editar" onClick={() => setEdicion({ ...f, pasos: f.pasos.map((p) => ({ ...p, usuario_id: p.usuario_id ?? '' })) })}><Pencil size={14} /></button>{' '}
                    <button className="icon-btn rojo" title="Eliminar" onClick={() => borrar(f)}><Trash2 size={14} /></button>
                  </td>
                </tr>
              ))}
              {!flujos.length && <tr><td colSpan={5} className="muted">Aún no hay flujos. Todos los permisos siguen la regla de la sede.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {!edicion && <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => setEdicion({ nombre: '', activo: true, pasos: [{ ...PASO_NUEVO }] })}><Plus size={14} /> Agregar flujo</button>}

      {edicion && (
        <div className="flujo-edicion">
          <div className="pol-grid">
            <label className="campo">Nombre del flujo
              <input value={edicion.nombre} onChange={(e) => setEdicion({ ...edicion, nombre: e.target.value })} placeholder="Ej. Jefe → TI → GH" />
            </label>
            <div className="campo">
              <span>Estado</span>
              <label className="checkbox"><input type="checkbox" checked={edicion.activo} onChange={(e) => setEdicion({ ...edicion, activo: e.target.checked })} /> Activo (si no, los tipos que lo usan siguen la regla de la sede)</label>
            </div>
          </div>
          <div className="tabla-wrap" style={{ marginTop: 10 }}>
            <table className="tabla">
              <thead><tr><th>Paso</th><th>Quién aprueba</th><th>Aprobar en Teams</th><th>Si no hay quién apruebe</th><th /></tr></thead>
              <tbody>
                {edicion.pasos.map((p, i) => (
                  <tr key={i} className="fila-edicion">
                    <td><b>{i + 1}</b></td>
                    <td>
                      <select value={p.aprobador} onChange={setPaso(i, 'aprobador')}>
                        {Object.entries(APROBADORES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                      </select>
                      {p.aprobador === 'usuario' && (
                        <select value={p.usuario_id} onChange={setPaso(i, 'usuario_id')} style={{ marginTop: 4 }}>
                          <option value="">— Elige a la persona —</option>
                          {personas.map((u) => <option key={u.id} value={u.id}>{u.nombre}{u.puesto ? ` · ${u.puesto}` : ''}</option>)}
                        </select>
                      )}
                    </td>
                    <td><label className="checkbox"><input type="checkbox" checked={p.teams} onChange={setPaso(i, 'teams')} /> Sí</label></td>
                    <td>
                      <select value={p.si_falta} onChange={setPaso(i, 'si_falta')}>
                        <option value="omitir">Omitir el paso</option>
                        <option value="bloquear">No dejar enviar la solicitud</option>
                      </select>
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <button className="icon-btn plain" title="Subir" disabled={i === 0} onClick={() => mover(i, -1)}><ArrowUp size={14} /></button>{' '}
                      <button className="icon-btn plain" title="Bajar" disabled={i === edicion.pasos.length - 1} onClick={() => mover(i, 1)}><ArrowDown size={14} /></button>{' '}
                      <button className="icon-btn rojo" title="Quitar" disabled={edicion.pasos.length === 1}
                        onClick={() => setEdicion({ ...edicion, pasos: edicion.pasos.filter((_, j) => j !== i) })}><Trash2 size={14} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 11, margin: '6px 0' }}>
            Por ahora Teams resuelve solo el primer paso de la cadena; los siguientes se aprueban en SIP-O (<i>Por aprobar</i>).
          </p>
          <div className="fila" style={{ gap: 8, marginTop: 8 }}>
            {edicion.pasos.length < 8 && <button className="btn btn-sm" onClick={() => setEdicion({ ...edicion, pasos: [...edicion.pasos, { ...PASO_NUEVO, aprobador: 'gh' }] })}><Plus size={14} /> Agregar paso</button>}
            <div className="espacio" />
            <button className="btn btn-sm" onClick={() => setEdicion(null)}><X size={14} /> Cancelar</button>
            <button className="btn btn-primary btn-sm" onClick={guardar}
              disabled={edicion.nombre.trim().length < 2 || edicion.pasos.some((p) => p.aprobador === 'usuario' && !p.usuario_id)}><Save size={14} /> Guardar flujo</button>
          </div>
        </div>
      )}
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
    </div>
  )
}
