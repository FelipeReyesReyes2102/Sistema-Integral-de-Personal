import { useEffect, useState } from 'react'
import { ListChecks, Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { textoLimite } from '../utils'

const NUEVO = {
  nombre: '', modalidad: 'horas', pide_nomina: true, limite_cantidad: '', limite_unidad: 'dias', limite_periodo: '',
  max_dias_solicitud: '', color: '#6d4c41', activo: true,
}
const PERIODOS = { '': 'Sin límite de periodo (en total)', mes: 'Por mes', anio: 'Por año' }

/** Tipos de permiso de la sede: los 4 base (se activan o desactivan) y los que agregue GH, con su límite. */
export default function ConfigTiposPermiso() {
  const [tipos, setTipos] = useState(null)
  const [edicion, setEdicion] = useState(null)
  const [msg, setMsg] = useState(null)

  const cargar = () => api('/tipos-permiso').then(setTipos).catch((e) => setMsg({ ok: false, t: e.message }))
  useEffect(() => { cargar() }, [])
  if (!tipos) return <div className="card" style={{ marginTop: 24 }}>{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>

  const setE = (k) => (e) => setEdicion({ ...edicion, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const conLimite = edicion && edicion.limite_cantidad !== '' && edicion.limite_cantidad !== null

  const aviso = (t) => {
    setMsg(t)
    cargar()
    window.dispatchEvent(new Event('politica:refrescar'))
  }

  async function guardar() {
    setMsg(null)
    const e = edicion
    const body = {
      nombre: e.nombre.trim(), modalidad: e.modalidad, pide_nomina: e.modalidad === 'horas' && e.pide_nomina, color: e.color,
      activo: e.activo,
      limite_cantidad: conLimite ? Number(e.limite_cantidad) : null,
      limite_unidad: e.modalidad === 'dias' ? 'dias' : e.limite_unidad,
      limite_periodo: e.limite_periodo || null,
      max_dias_solicitud: e.modalidad === 'dias' && e.max_dias_solicitud ? Number(e.max_dias_solicitud) : null,
    }
    try {
      if (e.id) await api(`/tipos-permiso/${e.id}`, { method: 'PUT', body })
      else await api('/tipos-permiso', { method: 'POST', body })
      setEdicion(null)
      aviso({ ok: true, t: `Tipo de permiso "${body.nombre}" guardado.` })
    } catch (err) {
      setMsg({ ok: false, t: err.message })
    }
  }

  async function borrar(t) {
    if (!window.confirm(`¿Eliminar el tipo de permiso "${t.nombre}"?`)) return
    setMsg(null)
    try {
      await api(`/tipos-permiso/${t.id}`, { method: 'DELETE' })
      aviso({ ok: true, t: `Tipo "${t.nombre}" eliminado.` })
    } catch (err) {
      setMsg({ ok: false, t: err.message })
    }
  }

  const editar = (t) => setEdicion({
    ...t, limite_cantidad: t.limite_cantidad ?? '', limite_periodo: t.limite_periodo || '', max_dias_solicitud: t.max_dias_solicitud ?? '',
  })

  return (
    <div className="card" style={{ marginTop: 24 }}>
      <h3 className="fila" style={{ gap: 8, marginBottom: 6 }}><ListChecks size={18} /> Tipos de permiso</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Agrega los permisos que usa la sede y define cuántos días (u horas) se permiten <b>por mes</b>, <b>por año</b> o
        en total. Los tipos base no se eliminan: desactívalos si la sede no los usa. Un tipo con solicitudes registradas solo
        se puede desactivar.
      </p>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Permiso</th><th>Se pide por</th><th>Tiempo en nómina</th><th>Límite</th><th>Máx. por solicitud</th><th>Estado</th><th /></tr></thead>
          <tbody>
            {tipos.map((t) => (edicion?.id === t.id ? null : (
              <tr key={t.id} style={{ opacity: t.activo ? 1 : 0.5 }}>
                <td>
                  <span className="reg-icono" style={{ background: t.color, width: 10, height: 10, marginRight: 6, display: 'inline-block', borderRadius: 3 }} />
                  <b>{t.nombre}</b>{t.base && <span className="muted"> (base)</span>}
                  {t.en_uso > 0 && <div className="muted" style={{ fontSize: 11 }}>{t.en_uso} solicitud(es)</div>}
                </td>
                <td>{t.modalidad === 'dias' ? 'Días (rango de fechas)' : 'Horas (un día, con horario)'}</td>
                <td>{t.modalidad === 'horas' && t.pide_nomina ? 'Lo indica el empleado' : <span className="muted">No aplica</span>}</td>
                <td>{textoLimite(t)}</td>
                <td>{t.modalidad === 'dias' ? `${t.max_dias_solicitud || 31} día(s)` : <span className="muted">—</span>}</td>
                <td>{t.activo ? 'Activo' : 'Inactivo'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="icon-btn" title="Editar" onClick={() => editar(t)}><Pencil size={14} /></button>{' '}
                  {!t.base && <button className="icon-btn rojo" title="Eliminar" onClick={() => borrar(t)}><Trash2 size={14} /></button>}
                </td>
              </tr>
            )))}
            {edicion && (
              <tr className="fila-edicion">
                <td>
                  <span className="fila" style={{ gap: 4 }}>
                    <input type="color" value={edicion.color} onChange={setE('color')} title="Color en el calendario" style={{ width: 34, padding: 0 }} />
                    <input value={edicion.nombre} onChange={setE('nombre')} placeholder="Ej. Día de cumpleaños" disabled={edicion.base} />
                  </span>
                </td>
                <td>
                  <select value={edicion.modalidad} onChange={setE('modalidad')} disabled={edicion.base}>
                    <option value="horas">Horas (un día)</option>
                    <option value="dias">Días (rango)</option>
                  </select>
                </td>
                <td>
                  {edicion.modalidad === 'horas'
                    ? <label className="checkbox"><input type="checkbox" checked={edicion.pide_nomina} onChange={setE('pide_nomina')} /> Pedir</label>
                    : <span className="muted">No aplica</span>}
                </td>
                <td>
                  <span className="fila" style={{ gap: 4, flexWrap: 'wrap' }}>
                    <input type="number" min={0.5} step={0.5} style={{ width: 64 }} value={edicion.limite_cantidad}
                      onChange={setE('limite_cantidad')} placeholder="Sin límite" title="Vacío = sin límite" />
                    {edicion.modalidad === 'horas' ? (
                      <select value={edicion.limite_unidad} onChange={setE('limite_unidad')} style={{ width: 92 }}>
                        <option value="dias">permisos</option>
                        <option value="horas">horas</option>
                      </select>
                    ) : <span>día(s)</span>}
                    <select value={edicion.limite_periodo} onChange={setE('limite_periodo')} disabled={!conLimite}>
                      {Object.entries(PERIODOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </span>
                </td>
                <td>
                  {edicion.modalidad === 'dias'
                    ? <input type="number" min={1} max={365} style={{ width: 70 }} value={edicion.max_dias_solicitud} onChange={setE('max_dias_solicitud')} placeholder="31" />
                    : <span className="muted">—</span>}
                </td>
                <td><label className="checkbox"><input type="checkbox" checked={edicion.activo} onChange={setE('activo')} /> Activo</label></td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="icon-btn verde" title="Guardar" onClick={guardar} disabled={edicion.nombre.trim().length < 2}><Save size={14} /></button>{' '}
                  <button className="icon-btn plain" title="Cancelar" onClick={() => setEdicion(null)}><X size={14} /></button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {!edicion && <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => setEdicion({ ...NUEVO })}><Plus size={14} /> Agregar tipo de permiso</button>}
      <p className="muted" style={{ fontSize: 12, margin: '8px 0 0' }}>
        En permisos por horas, el límite cuenta <b>permisos</b> (cada solicitud es uno) u <b>horas</b>. En permisos por días cuenta los
        días laborales. Se toman en cuenta los borradores, las solicitudes pendientes y las validadas.
      </p>
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
    </div>
  )
}
