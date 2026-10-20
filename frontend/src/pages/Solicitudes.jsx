import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Eye, PenLine, X } from 'lucide-react'
import { api } from '../api'
import DetalleConsulta from '../components/DetalleConsulta'
import Modal from '../components/Modal'
import { ESTADOS, RESULTADOS_CONSULTA, ROLES, TIPOS_NOMINA, TIPOS_PERMISO, TIPOS_PERMISO_SOLICITABLES, fmtFecha, hhmm, num } from '../utils'

/**
 * Bandeja para aprobar o rechazar vacaciones y permisos.
 * modo="jefe": solicitudes donde el usuario es el jefe aprobador.
 * modo="admin": todas las solicitudes de la empresa.
 */
export default function Solicitudes({ modo = 'jefe' }) {
  const [tab, setTab] = useState('vacaciones')
  const [estado, setEstado] = useState('solicitado')
  const [lista, setLista] = useState([])
  const [buscar, setBuscar] = useState('')
  const [tipo, setTipo] = useState('')
  const [verConsulta, setVerConsulta] = useState(null)
  const [rechazo, setRechazo] = useState(null)
  const [validarPermiso, setValidarPermiso] = useState(null)
  const [firma, setFirma] = useState(null)

  function verFirma(s) {
    api(`/${tab}/${s.id}/firma`).then((r) => setFirma({ nombre: s.usuario_nombre, img: r.firma })).catch((e) => alert(e.message))
  }
  const [error, setError] = useState('')
  const admin = modo === 'admin'
  const navigate = useNavigate()

  const cargar = () => {
    setError('')
    setLista([])
    if (tab === 'consultas') {
      api('/consultas', { query: { todos: true } }).then(setLista).catch((e) => setError(e.message))
      return
    }
    const query = admin ? { todos: true, estado } : { por_aprobar: true, estado }
    if (tab === 'permisos' && tipo) query.tipo = tipo
    api(`/${tab}`, { query }).then(setLista).catch((e) => setError(e.message))
  }
  useEffect(cargar, [tab, estado, modo, tipo])

  // Pendientes por pestaña (círculo rojo), se actualiza al aprobar/rechazar
  const [pend, setPend] = useState({})
  useEffect(() => {
    const leer = () => api('/pendientes').then(setPend).catch(() => {})
    leer()
    window.addEventListener('pendientes:refrescar', leer)
    return () => window.removeEventListener('pendientes:refrescar', leer)
  }, [])
  const cuenta = (t) => (admin ? pend[`todas_${t}`] : pend[t]) || 0
  const marca = (t) => cuenta(t) > 0 && <span className="badge tab-badge" title={`${cuenta(t)} por revisar`}>{cuenta(t)}</span>

  async function ejecutar(ruta, body) {
    try {
      await api(ruta, { method: 'POST', body })
      setRechazo(null)
      setValidarPermiso(null)
      cargar()
      window.dispatchEvent(new Event('pendientes:refrescar'))
    } catch (e) {
      alert(e.message)
    }
  }

  const filtrada = lista.filter((s) => !buscar || (s.usuario_nombre || s.paciente_nombre)?.toLowerCase().includes(buscar.toLowerCase()))

  return (
    <div className="card">
      <div className="fila" style={{ marginBottom: 14 }}>
        <div className="cal-nav">
          <button style={{ fontWeight: tab === 'vacaciones' ? 700 : 400, color: tab === 'vacaciones' ? 'var(--primary)' : '' }}
            onClick={() => setTab('vacaciones')}>Vacaciones{marca('vacaciones')}</button>
          <button style={{ fontWeight: tab === 'permisos' ? 700 : 400, color: tab === 'permisos' ? 'var(--primary)' : '' }}
            onClick={() => setTab('permisos')}>Permisos y home office{marca('permisos')}</button>
          {admin && (
            <button style={{ fontWeight: tab === 'consultas' ? 700 : 400, color: tab === 'consultas' ? 'var(--primary)' : '' }}
              onClick={() => setTab('consultas')}>Consultas médicas</button>
          )}
        </div>
        {tab !== 'consultas' && (
          <select style={{ width: 180 }} value={estado} onChange={(e) => setEstado(e.target.value)}>
            <option value="">Todos los estados</option>
            {Object.entries(ESTADOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        )}
        {tab === 'permisos' && (
          <select style={{ width: 200 }} value={tipo} onChange={(e) => setTipo(e.target.value)}>
            <option value="">Todos los tipos</option>
            {Object.entries(TIPOS_PERMISO_SOLICITABLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        )}
        <input style={{ width: 220 }} placeholder="Buscar empleado…" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
      </div>
      {error && <div className="alerta error">{error}</div>}
      {tab === 'consultas' ? (
        <div className="tabla-wrap">
          <table className="tabla">
            <thead><tr><th>Fecha</th><th>Paciente</th><th>Síntomas</th><th>Medicamento</th><th>Resultado</th><th>Atendió</th><th /></tr></thead>
            <tbody>
              {filtrada.length === 0 && <tr><td colSpan={7} className="muted" style={{ textAlign: 'center' }}>Sin consultas</td></tr>}
              {lista.filter((c) => !buscar || c.paciente_nombre?.toLowerCase().includes(buscar.toLowerCase())).map((c) => (
                <tr key={c.id}>
                  <td style={{ whiteSpace: 'nowrap' }}>{fmtFecha(c.fecha)} · {hhmm(c.hora_inicio)}</td>
                  <td>{c.paciente_nombre}<div className="muted" style={{ fontSize: 12 }}>No. {c.paciente_numero} · {ROLES[c.paciente_rol]}</div></td>
                  <td className="muted" style={{ maxWidth: 260 }}>{c.sintomas}</td>
                  <td>{c.medicamentos?.map((m) => m.nombre).join(', ') || '—'}</td>
                  <td>{RESULTADOS_CONSULTA[c.resultado]}</td>
                  <td className="muted">{c.medico_nombre}</td>
                  <td><button className="icon-btn" title="Ver" onClick={() => setVerConsulta(c.id)}><Eye size={16} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            {tab === 'vacaciones' ? (
              <tr><th>Empleado</th><th>Periodo</th><th>Fechas</th><th>Días</th><th>Comentario</th><th>Estado</th><th /></tr>
            ) : (
              <tr><th>Empleado</th><th>Tipo</th><th>Fecha</th><th>Horario</th><th>Motivo</th><th>Estado</th><th /></tr>
            )}
          </thead>
          <tbody>
            {filtrada.length === 0 && <tr><td colSpan={7} className="muted" style={{ textAlign: 'center' }}>Sin solicitudes</td></tr>}
            {filtrada.map((s) => (
              <tr key={s.id}>
                <td>
                  <div className="fila" style={{ gap: 6, flexWrap: 'nowrap' }}>
                    <button className="icon-btn plain" title="Ver vacaciones tomadas y saldo"
                      onClick={() => navigate(`${admin ? '/empleados' : '/mi-equipo'}/${s.usuario_id}/vacaciones`)}>
                      <Eye size={16} />
                    </button>
                    <div>
                      {s.usuario_nombre}
                      {admin && <div className="muted" style={{ fontSize: 12 }}>Jefe: {s.aprobador_nombre || 'Administración'}</div>}
                    </div>
                  </div>
                </td>
                {tab === 'vacaciones' ? (
                  <>
                    <td>{s.periodo_nombre}</td>
                    <td>{fmtFecha(s.fecha_inicio)} - {fmtFecha(s.fecha_fin)}</td>
                    <td>{s.por_horas ? <><b>{num(s.horas)} h</b> <span className="muted">(por horas)</span></> : <>{s.dias_habiles} d <span className="muted">({num(s.horas)} h)</span></>}</td>
                    <td className="muted">{s.planeada && <span className="chip" style={{ marginRight: 4 }}>Planeada por GH</span>}{s.comentario}</td>
                  </>
                ) : (
                  <>
                    <td>{TIPOS_PERMISO[s.tipo]}</td>
                    <td>{fmtFecha(s.fecha)}{s.tipo === 'home_office' && s.fecha_fin && s.fecha_fin !== s.fecha ? ` → ${fmtFecha(s.fecha_fin)}` : ''}</td>
                    <td>{s.tipo === 'home_office'
                      ? <span className="muted">{s.dias ?? '—'} día(s) laborales</span>
                      : <>{hhmm(s.hora_inicio)} - {hhmm(s.hora_fin)} <span className="muted">({num(s.horas)} h)</span></>}</td>
                    <td className="muted">
                      {s.motivo}
                      {s.tipo_nomina && <div style={{ fontSize: 11 }}>{TIPOS_NOMINA[s.tipo_nomina]}{s.departamento && ` · ${s.departamento}`}</div>}
                    </td>
                  </>
                )}
                <td>
                  <span className={`pill ${s.estado}`}>{s.falta_gh ? 'Aprobada por el jefe' : ESTADOS[s.estado]}</span>
                  {s.falta_gh && <div className="muted" style={{ fontSize: 11 }}>{s.aprobado_jefe_nombre} · falta GH</div>}
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {s.tiene_firma && (
                    <button className="btn btn-sm" style={{ marginBottom: 4 }} onClick={() => verFirma(s)}><PenLine size={14} /> Firma</button>
                  )}
                  {s.estado === 'solicitado' && (admin || !s.falta_gh) && (
                    <div className="fila" style={{ flexWrap: 'nowrap' }}>
                      <button className="btn btn-sm btn-success"
                        onClick={() => (tab === 'permisos' ? setValidarPermiso(s) : ejecutar(`/vacaciones/${s.id}/validar`))}>
                        <Check size={14} /> {admin || !s.requiere_gh ? 'Validar' : 'Aprobar'}
                      </button>
                      <button className="btn btn-sm btn-danger" onClick={() => setRechazo({ s, motivo: '' })}>
                        <X size={14} /> Rechazar
                      </button>
                    </div>
                  )}
                  {s.estado === 'validado' && (
                    <button className="btn btn-sm" onClick={() => window.confirm('¿Cancelar la solicitud validada? Se devolverá el saldo.') && ejecutar(`/${tab}/${s.id}/cancelar`)}>
                      Cancelar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      )}
      {verConsulta && <DetalleConsulta consultaId={verConsulta} onClose={() => setVerConsulta(null)} />}
      {firma && (
        <Modal titulo={`Firma de ${firma.nombre}`} onClose={() => setFirma(null)}
          pie={<button className="btn" onClick={() => setFirma(null)}>Cerrar</button>}>
          {firma.img ? <img className="firma-img" style={{ height: 140 }} src={firma.img} alt="Firma" /> : 'Sin firma'}
        </Modal>
      )}
      {rechazo && (
        <Modal titulo="Rechazar solicitud" onClose={() => setRechazo(null)}
          pie={<>
            <button className="btn" onClick={() => setRechazo(null)}>Cancelar</button>
            <button className="btn btn-danger" onClick={() => ejecutar(`/${tab}/${rechazo.s.id}/rechazar`, { motivo: rechazo.motivo })}>Rechazar</button>
          </>}>
          <p>Solicitud de <b>{rechazo.s.usuario_nombre}</b></p>
          <label className="campo">Motivo del rechazo
            <textarea rows={3} value={rechazo.motivo} onChange={(e) => setRechazo({ ...rechazo, motivo: e.target.value })} />
          </label>
        </Modal>
      )}
      {validarPermiso && (
        <Modal titulo="Validar permiso" onClose={() => setValidarPermiso(null)}
          pie={<>
            <button className="btn" onClick={() => setValidarPermiso(null)}>Cancelar</button>
            <button className="btn btn-success"
              onClick={() => ejecutar(`/permisos/${validarPermiso.id}/validar`, { observaciones: validarPermiso.obs || null })}>Validar</button>
          </>}>
          <p><b>{validarPermiso.usuario_nombre}</b> · {TIPOS_PERMISO[validarPermiso.tipo]} · {fmtFecha(validarPermiso.fecha)} {hhmm(validarPermiso.hora_inicio)}-{hhmm(validarPermiso.hora_fin)}</p>
          <label className="campo">
            {validarPermiso.tipo === 'consulta_medica' ? 'Observaciones del médico de planta (opcional)' : 'Observaciones (opcional)'}
            <textarea rows={3} value={validarPermiso.obs || ''} onChange={(e) => setValidarPermiso({ ...validarPermiso, obs: e.target.value })} />
          </label>
        </Modal>
      )}
    </div>
  )
}
