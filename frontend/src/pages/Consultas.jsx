import { useEffect, useState } from 'react'
import { Eye, Pencil, Plus, Trash2 } from 'lucide-react'
import { api } from '../api'
import ConsultaModal from '../components/ConsultaModal'
import BitacoraConsultas from '../components/BitacoraConsultas'
import DetalleConsulta from '../components/DetalleConsulta'
import { ESTADOS_INCAPACIDAD, RESULTADOS_CONSULTA, ROLES, fmtFecha, hhmm, toISO } from '../utils'

/** Bitácora del servicio médico de planta. */
export default function Consultas() {
  const hace30 = toISO(new Date(Date.now() - 30 * 864e5))
  const [filtros, setFiltros] = useState({ desde: hace30, hasta: '', rol: '', q: '' })
  const [lista, setLista] = useState([])
  const [hoy, setHoy] = useState(null)
  const [modal, setModal] = useState(null) // {tipo: 'nueva'|'editar'|'ver', consulta}
  const [error, setError] = useState('')
  const [vista, setVista] = useState('consultas')

  const cargar = () => {
    api('/consultas', { query: { todos: true, ...filtros } }).then(setLista).catch((e) => setError(e.message))
    api('/consultas/resumen/hoy').then(setHoy).catch(() => {})
  }
  useEffect(() => { const t = setTimeout(cargar, 200); return () => clearTimeout(t) }, [filtros])

  const f = (k) => (e) => setFiltros({ ...filtros, [k]: e.target.value })

  async function eliminar(c) {
    if (!window.confirm(`¿Eliminar la consulta de ${c.paciente_nombre} del ${fmtFecha(c.fecha)}?`)) return
    try {
      await api(`/consultas/${c.id}`, { method: 'DELETE' })
      cargar()
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <>
      <div className="card fila" style={{ gap: 40, marginBottom: 16 }}>
        <div className="stat"><b>{hoy?.consultas_hoy ?? '—'}</b><span>Consultas hoy</span></div>
        <div className="stat"><b>{hoy?.enviados_a_casa_hoy ?? '—'}</b><span>Enviados a casa hoy</span></div>
        <div className="stat"><b>{lista.length}</b><span>Consultas en el periodo filtrado</span></div>
        <div className="espacio" />
        <button className="btn btn-primary" onClick={() => setModal({ tipo: 'nueva' })}><Plus size={16} /> Registrar consulta</button>
      </div>

      <div className="tabs" style={{ marginBottom: 12 }}>
        <button className={vista === 'consultas' ? 'activo' : ''} onClick={() => setVista('consultas')}>CONSULTAS</button>
        <button className={vista === 'bitacora' ? 'activo' : ''} onClick={() => setVista('bitacora')}>BITÁCORA</button>
      </div>
      {vista === 'bitacora' && <BitacoraConsultas onVer={(id) => setModal({ tipo: 'ver', consulta: { id } })} />}

      {vista === 'consultas' && <div className="card">
        <div className="fila" style={{ marginBottom: 14 }}>
          <label className="campo" style={{ width: 150 }}>Desde<input type="date" value={filtros.desde} onChange={f('desde')} /></label>
          <label className="campo" style={{ width: 150 }}>Hasta<input type="date" value={filtros.hasta} onChange={f('hasta')} /></label>
          <label className="campo" style={{ width: 170 }}>Tipo de usuario
            <select value={filtros.rol} onChange={f('rol')}>
              <option value="">Todos</option>
              {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="campo" style={{ flex: 1, minWidth: 200 }}>Buscar
            <input value={filtros.q} onChange={f('q')} placeholder="Nombre o número de empleado" />
          </label>
        </div>
        {error && <div className="alerta error">{error}</div>}
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr><th>Fecha</th><th>Horario</th><th>Paciente</th><th>Síntomas</th><th>Medicamento</th><th>Resultado</th><th>Incapacidad</th><th>Atendió</th><th /></tr>
            </thead>
            <tbody>
              {lista.length === 0 && <tr><td colSpan={9} className="muted" style={{ textAlign: 'center', padding: 24 }}>Sin consultas en el periodo.</td></tr>}
              {lista.map((c) => (
                <tr key={c.id}>
                  <td style={{ whiteSpace: 'nowrap' }}>{fmtFecha(c.fecha)}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{hhmm(c.hora_inicio)}{c.hora_fin ? ` - ${hhmm(c.hora_fin)}` : ''}</td>
                  <td>
                    <div>{c.paciente_nombre}</div>
                    <div className="muted" style={{ fontSize: 12 }}>No. {c.paciente_numero} · {ROLES[c.paciente_rol]}{c.paciente_departamento ? ` · ${c.paciente_departamento}` : ''}</div>
                  </td>
                  <td className="muted" style={{ maxWidth: 260 }}>{c.sintomas}</td>
                  <td>{c.medicamentos.map((m) => m.nombre).join(', ') || '—'}</td>
                  <td>
                    <span className={`pill ${c.resultado === 'regresa_labores' ? 'validado' : c.resultado === 'envia_casa' ? 'solicitado' : 'borrador'}`}>
                      {RESULTADOS_CONSULTA[c.resultado]}
                    </span>
                  </td>
                  <td>
                    {c.incapacidad ? (
                      <>
                        <span className={`pill ${c.incapacidad.estado}`}>{ESTADOS_INCAPACIDAD[c.incapacidad.estado]}</span>
                        <div className="muted" style={{ fontSize: 11 }}>
                          {c.incapacidad.dias} día(s){c.incapacidad.estado !== 'solicitado' && c.incapacidad.revisado_por_nombre ? ` · ${c.incapacidad.revisado_por_nombre}` : ''}
                        </div>
                      </>
                    ) : <span className="muted">—</span>}
                  </td>
                  <td className="muted">{c.medico_nombre}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <button className="icon-btn" title="Ver" onClick={() => setModal({ tipo: 'ver', consulta: c })}><Eye size={16} /></button>{' '}
                    <button className="icon-btn" title="Editar" onClick={() => setModal({ tipo: 'editar', consulta: c })}><Pencil size={16} /></button>{' '}
                    <button className="icon-btn rojo" title="Eliminar" onClick={() => eliminar(c)}><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>}

      {(modal?.tipo === 'nueva' || modal?.tipo === 'editar') && (
        <ConsultaModal consulta={modal.consulta} onClose={() => setModal(null)} onSaved={() => { setModal(null); cargar() }} />
      )}
      {modal?.tipo === 'ver' && <DetalleConsulta consultaId={modal.consulta.id} onClose={() => setModal(null)} />}
    </>
  )
}
