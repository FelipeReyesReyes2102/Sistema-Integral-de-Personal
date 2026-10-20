import { useEffect, useState } from 'react'
import { Eye } from 'lucide-react'
import { api } from '../api'
import { ESTADOS_INCAPACIDAD, ROLES, toISO } from '../utils'

// Color del evento: registro (azul), cambio (ámbar), baja o rechazo (rojo), validación (verde)
const CLASE = {
  consulta_registrada: 'solicitado', consulta_editada: 'borrador', consulta_eliminada: 'rechazado', consulta_vista_admin: 'borrador',
  incapacidad_generada: 'solicitado', incapacidad_modificada: 'borrador', incapacidad_quitada: 'rechazado',
  incapacidad_validada: 'validado', incapacidad_rechazada: 'rechazado',
}

/** Bitácora del servicio médico: quién registró cada consulta e incapacidad y quién la validó o rechazó. */
export default function BitacoraConsultas({ onVer }) {
  const [f, setF] = useState({ desde: toISO(new Date(Date.now() - 30 * 864e5)), hasta: '', tipo: '', q: '' })
  const [lista, setLista] = useState([])
  const [error, setError] = useState('')
  useEffect(() => {
    const t = setTimeout(() => {
      api('/consultas/bitacora', { query: f }).then((r) => { setLista(r); setError('') }).catch((e) => setError(e.message))
    }, 200)
    return () => clearTimeout(t)
  }, [f])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  return (
    <div className="card">
      <div className="fila" style={{ marginBottom: 14 }}>
        <label className="campo" style={{ width: 150 }}>Desde<input type="date" value={f.desde} onChange={set('desde')} /></label>
        <label className="campo" style={{ width: 150 }}>Hasta<input type="date" value={f.hasta} onChange={set('hasta')} /></label>
        <label className="campo" style={{ width: 190 }}>Registros
          <select value={f.tipo} onChange={set('tipo')}>
            <option value="">Consultas e incapacidades</option>
            <option value="consulta">Solo consultas</option>
            <option value="incapacidad">Solo incapacidades</option>
          </select>
        </label>
        <label className="campo" style={{ flex: 1, minWidth: 200 }}>Buscar
          <input value={f.q} onChange={set('q')} placeholder="Paciente, nómina, quién lo hizo o folio" />
        </label>
      </div>
      {error && <div className="alerta error">{error}</div>}
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Fecha y hora</th><th>Evento</th><th>Paciente</th><th>Realizó</th><th>Detalle</th><th>Incapacidad hoy</th><th /></tr></thead>
          <tbody>
            {lista.length === 0 && <tr><td colSpan={7} className="muted" style={{ textAlign: 'center', padding: 24 }}>Sin registros en el periodo.</td></tr>}
            {lista.map((b) => (
              <tr key={b.id}>
                <td style={{ whiteSpace: 'nowrap' }}>{new Date(`${b.fecha.slice(0, 19)}Z`).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })}</td>
                <td><span className={`pill ${CLASE[b.evento] || ''}`}>{b.evento_nombre}</span></td>
                <td>{b.paciente_nombre}<div className="muted" style={{ fontSize: 12 }}>No. {b.paciente_numero}</div></td>
                <td>{b.actor_nombre}<div className="muted" style={{ fontSize: 12 }}>{ROLES[b.actor_rol] || ''}</div></td>
                <td className="muted" style={{ maxWidth: 380, fontSize: 12 }}>{(b.detalle || '').replace(/^consulta \d+ · /, '')}</td>
                <td>{b.incapacidad_estado ? <span className={`pill ${b.incapacidad_estado}`}>{ESTADOS_INCAPACIDAD[b.incapacidad_estado]}</span> : <span className="muted">—</span>}</td>
                <td>{b.consulta_id && <button className="icon-btn" title="Ver consulta" onClick={() => onVer(b.consulta_id)}><Eye size={16} /></button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        Registro de lo que hace el servicio médico (alta, cambios y bajas de consultas e incapacidades) y de las validaciones o
        rechazos del jefe y GH. No incluye síntomas, diagnóstico ni medicamentos.
      </p>
    </div>
  )
}
