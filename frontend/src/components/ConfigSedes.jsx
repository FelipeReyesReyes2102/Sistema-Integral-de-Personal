import { useEffect, useState } from 'react'
import { Building2, CloudDownload, Pencil, Plus, Save, X } from 'lucide-react'
import { api } from '../api'

const ZONAS = [
  'America/Mexico_City', 'America/Monterrey', 'America/Tijuana', 'America/Cancun', 'America/Hermosillo',
  'America/Bogota', 'America/Lima', 'America/Santiago', 'America/Argentina/Buenos_Aires', 'America/New_York',
]
const NUEVA = { nombre: '', ubicacion_microsoft: '', zona_horaria: 'America/Mexico_City', activa: true }

/** Sedes (solo super administrador): alta, edición e importación desde la "Ubicación del trabajo" de Microsoft. */
export default function ConfigSedes() {
  const [sedes, setSedes] = useState([])
  const [edit, setEdit] = useState(null) // {id?, ...campos}
  const [msg, setMsg] = useState(null)
  const [ocupado, setOcupado] = useState(false)

  const cargar = () => api('/sedes').then(setSedes).catch((e) => setMsg({ ok: false, t: e.message }))
  useEffect(() => { cargar() }, [])

  async function guardar() {
    setMsg(null)
    try {
      const body = { ...edit, ubicacion_microsoft: edit.ubicacion_microsoft || null }
      if (edit.id) await api(`/sedes/${edit.id}`, { method: 'PUT', body })
      else await api('/sedes', { method: 'POST', body })
      setEdit(null)
      setMsg({ ok: true, t: 'Sede guardada. Recarga la página para verla en el selector de sedes.' })
      cargar()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  async function importar() {
    setMsg(null)
    setOcupado(true)
    try {
      const r = await api('/sedes/importar-microsoft', { method: 'POST' })
      const total = Object.keys(r.ubicaciones).length
      setMsg({
        ok: true,
        t: r.creadas.length
          ? `Se crearon ${r.creadas.length} sede(s): ${r.creadas.join(', ')}. Revisa su zona horaria.`
          : `Microsoft tiene ${total} ubicación(es) de trabajo y todas ya existen como sede.`,
      })
      cargar()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado(false)
    }
  }

  const set = (k) => (e) => setEdit({ ...edit, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  return (
    <div className="card" style={{ marginTop: 24 }}>
      <div className="fila" style={{ marginBottom: 6 }}>
        <h3 className="fila" style={{ gap: 8 }}><Building2 size={18} /> Sedes</h3>
        <div className="espacio" />
        <button className="btn" onClick={importar} disabled={ocupado}><CloudDownload size={15} /> Importar desde Microsoft</button>
        <button className="btn btn-primary" onClick={() => setEdit({ ...NUEVA })}><Plus size={15} /> Nueva sede</button>
      </div>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Cada sede tiene su personal, administradores, turnos, grupos, festivos, avisos a caseta y zona horaria. La sede de cada
        empleado se toma de su <b>Ubicación del trabajo</b> en Microsoft. Solo un super administrador crea sedes y cambia a un
        empleado de sede.
      </p>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Sede</th><th>Ubicación en Microsoft</th><th>Zona horaria</th><th>Empleados</th><th>Estado</th><th /></tr></thead>
          <tbody>
            {sedes.map((s) => (
              <tr key={s.id} style={{ opacity: s.activa ? 1 : 0.55 }}>
                <td><b>{s.nombre}</b></td>
                <td className="muted">{s.ubicacion_microsoft || '—'}</td>
                <td>{s.zona_horaria}</td>
                <td>{s.empleados}</td>
                <td>{s.activa ? 'Activa' : 'Inactiva'}</td>
                <td><button className="icon-btn" title="Editar" onClick={() => setEdit({ ...s, ubicacion_microsoft: s.ubicacion_microsoft || '' })}><Pencil size={15} /></button></td>
              </tr>
            ))}
            {edit && (
              <tr className="fila-edicion">
                <td><input value={edit.nombre} onChange={set('nombre')} placeholder="O-Tek Colombia - Medellín" /></td>
                <td><input value={edit.ubicacion_microsoft} onChange={set('ubicacion_microsoft')} placeholder="Igual que en Microsoft" /></td>
                <td>
                  <select value={edit.zona_horaria} onChange={set('zona_horaria')}>
                    {[...new Set([edit.zona_horaria, ...ZONAS])].map((z) => <option key={z} value={z}>{z}</option>)}
                  </select>
                </td>
                <td className="muted">{edit.id ? edit.empleados : '—'}</td>
                <td><label className="checkbox"><input type="checkbox" checked={edit.activa} onChange={set('activa')} /> Activa</label></td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="icon-btn verde" title="Guardar" onClick={guardar}><Save size={15} /></button>{' '}
                  <button className="icon-btn plain" title="Cancelar" onClick={() => setEdit(null)}><X size={15} /></button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
    </div>
  )
}
