import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../api'
import SedeActual from '../components/SedeActual'
import { fmtFecha } from '../utils'

const APLICA = { todos: 'Todos', oficina: 'Solo oficinas', planta: 'Solo planta' }

export default function Festivos() {
  const [anio, setAnio] = useState(new Date().getFullYear())
  const [lista, setLista] = useState([])
  const [nuevo, setNuevo] = useState({ fecha: '', nombre: '', aplica_a: 'todos' })
  const [error, setError] = useState('')
  const cargar = () => api('/festivos', { query: { anio } }).then(setLista)
  useEffect(() => { cargar() }, [anio])

  async function agregar(e) {
    e.preventDefault()
    setError('')
    try {
      await api('/festivos', { method: 'POST', body: nuevo })
      setNuevo({ fecha: '', nombre: '', aplica_a: 'todos' })
      cargar()
    } catch (err) {
      setError(err.message)
    }
  }

  async function cambiarAplica(f, aplica_a) {
    await api(`/festivos/${f.id}`, { method: 'PUT', body: { fecha: f.fecha, nombre: f.nombre, aplica_a } })
    cargar()
  }

  async function borrar(f) {
    if (!window.confirm(`¿Eliminar ${f.nombre}?`)) return
    await api(`/festivos/${f.id}`, { method: 'DELETE' })
    cargar()
  }

  return (
    <div className="card">
      <SedeActual que="Los festivos nuevos" />
      <p className="muted" style={{ marginTop: 0 }}>Cada sede tiene sus propios días festivos; no se descuentan del saldo de vacaciones.</p>
      <form className="fila" onSubmit={agregar} style={{ marginBottom: 14 }}>
        <input type="date" style={{ width: 160 }} value={nuevo.fecha} onChange={(e) => setNuevo({ ...nuevo, fecha: e.target.value })} required />
        <input style={{ maxWidth: 260 }} placeholder="Nombre del festivo" value={nuevo.nombre} onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })} required />
        <select style={{ width: 150 }} value={nuevo.aplica_a} onChange={(e) => setNuevo({ ...nuevo, aplica_a: e.target.value })}>
          {Object.entries(APLICA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <button className="btn btn-primary"><Plus size={16} /> Agregar</button>
        <div className="espacio" />
        <div className="cal-nav">
          <button type="button" onClick={() => setAnio(anio - 1)}>‹</button>
          <button type="button" style={{ fontWeight: 700 }}>{anio}</button>
          <button type="button" onClick={() => setAnio(anio + 1)}>›</button>
        </div>
      </form>
      {error && <div className="alerta error">{error}</div>}
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Fecha</th><th>Festivo</th><th>Aplica a</th><th /></tr></thead>
          <tbody>
            {lista.length === 0 && <tr><td colSpan={4} className="muted">Sin festivos registrados para {anio}.</td></tr>}
            {lista.map((f) => (
              <tr key={f.id}>
                <td>{fmtFecha(f.fecha)}</td>
                <td>{f.nombre}{f.sede_nombre && <span className="muted" style={{ fontSize: 11 }}> · {f.sede_nombre}</span>}</td>
                <td>
                  <select style={{ width: 150 }} value={f.aplica_a} onChange={(e) => cambiarAplica(f, e.target.value)}>
                    {Object.entries(APLICA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td><button className="icon-btn rojo" onClick={() => borrar(f)}><Trash2 size={16} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
