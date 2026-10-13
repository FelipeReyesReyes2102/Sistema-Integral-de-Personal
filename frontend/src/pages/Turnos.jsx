import { useEffect, useState } from 'react'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { api } from '../api'
import Modal from '../components/Modal'
import RotacionTurnos from '../components/RotacionTurnos'
import SedeActual from '../components/SedeActual'
import { hhmm } from '../utils'

const VACIO = { nombre: '', hora_entrada: '07:00', hora_salida: '19:00', horas_jornada: 12, descripcion: '', activo: true }

export default function Turnos() {
  const [lista, setLista] = useState([])
  const [form, setForm] = useState(null)
  const [error, setError] = useState('')
  const cargar = () => api('/turnos').then(setLista)
  useEffect(() => { cargar() }, [])

  async function guardar() {
    setError('')
    const body = { ...form, horas_jornada: Number(form.horas_jornada) }
    try {
      if (form.id) await api(`/turnos/${form.id}`, { method: 'PUT', body })
      else await api('/turnos', { method: 'POST', body })
      setForm(null)
      cargar()
    } catch (e) {
      setError(e.message)
    }
  }

  async function borrar(t) {
    if (!window.confirm(`¿Eliminar el turno ${t.nombre}? Los empleados quedarán sin turno.`)) return
    await api(`/turnos/${t.id}`, { method: 'DELETE' }).catch((e) => alert(e.message))
    cargar()
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  return (
    <>
    <SedeActual que="Los turnos nuevos y la rotación" />
    <div className="card">
      <div className="fila" style={{ marginBottom: 14 }}>
        <div className="muted">Define los horarios. Se usan para prellenar permisos y limitar su duración a la jornada.</div>
        <div className="espacio" />
        <button className="btn btn-primary" onClick={() => setForm(VACIO)}><Plus size={16} /> Nuevo turno</button>
      </div>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Turno</th><th>Entrada</th><th>Salida</th><th>Jornada</th><th>Descripción</th><th>Estado</th><th /></tr></thead>
          <tbody>
            {lista.map((t) => (
              <tr key={t.id}>
                <td><b>{t.nombre}</b>{t.sede_nombre && <div className="muted" style={{ fontSize: 11 }}>{t.sede_nombre}</div>}</td>
                <td>{hhmm(t.hora_entrada)}</td>
                <td>{hhmm(t.hora_salida)}</td>
                <td>{t.horas_jornada} h</td>
                <td className="muted">{t.descripcion}</td>
                <td>{t.activo ? 'Activo' : 'Inactivo'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="icon-btn" onClick={() => setForm({ ...t, hora_entrada: hhmm(t.hora_entrada), hora_salida: hhmm(t.hora_salida) })}><Pencil size={16} /></button>{' '}
                  <button className="icon-btn rojo" onClick={() => borrar(t)}><Trash2 size={16} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {form && (
        <Modal titulo={form.id ? 'Editar turno' : 'Nuevo turno'} onClose={() => setForm(null)}
          pie={<><button className="btn" onClick={() => setForm(null)}>Cancelar</button><button className="btn btn-primary" onClick={guardar}>Guardar</button></>}>
          <div className="form-grid">
            <label className="campo full">Nombre<input value={form.nombre} onChange={set('nombre')} /></label>
            <label className="campo">Hora de entrada<input type="time" value={form.hora_entrada} onChange={set('hora_entrada')} /></label>
            <label className="campo">Hora de salida<input type="time" value={form.hora_salida} onChange={set('hora_salida')} /></label>
            <label className="campo">Horas por jornada<input type="number" min={1} max={24} value={form.horas_jornada} onChange={set('horas_jornada')} /></label>
            <label className="checkbox" style={{ alignSelf: 'end' }}><input type="checkbox" checked={form.activo} onChange={set('activo')} /> Activo</label>
            <label className="campo full">Descripción<input value={form.descripcion || ''} onChange={set('descripcion')} /></label>
            {error && <div className="full alerta error">{error}</div>}
          </div>
        </Modal>
      )}
    </div>
    <RotacionTurnos onCambio={cargar} />
    </>
  )
}
