import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Eye, PenLine, X } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import DetalleConsulta from '../components/DetalleConsulta'
import FormatoEquipo from '../components/FormatoEquipo'
import TablaSalidas from '../components/TablaSalidas'
import Modal from '../components/Modal'
import {
  ESTADOS, ESTADOS_INCAPACIDAD, RESULTADOS_CONSULTA, ROLES, TIPOS_INCAPACIDAD, TIPOS_NOMINA, TIPOS_PERMISO_SOLICITABLES, fmtFecha,
  esTI, nombreTipo, hhmm, num,
} from '../utils'

/**
 * Bandeja para aprobar o rechazar vacaciones, permisos e incapacidades.
 * modo="jefe": solicitudes donde el usuario es el jefe aprobador.
 * modo="admin": todas las solicitudes de la empresa.
 */
const PESTANAS = [
  ['vacaciones', 'Vacaciones'], ['permisos', 'Permisos y home office'], ['incapacidades', 'Incapacidades'],
  ['equipos', 'Salida de equipo'], ['consultas', 'Consultas médicas'],
]

export default function Solicitudes({ modo = 'jefe' }) {
  const [tab, setTab] = useState('vacaciones')
  const [estado, setEstado] = useState('solicitado')
  const [lista, setLista] = useState([])
  const [buscar, setBuscar] = useState('')
  const [tipo, setTipo] = useState('')
  const [verConsulta, setVerConsulta] = useState(null)
  const [rechazo, setRechazo] = useState(null)
  const [sinMotivo, setSinMotivo] = useState([])
  const [validarPermiso, setValidarPermiso] = useState(null)
  const [validarInc, setValidarInc] = useState(null)
  const [formatoEq, setFormatoEq] = useState(null)
  const [firma, setFirma] = useState(null)

  function verFirma(s) {
    api(`/${tab}/${s.id}/firma`).then((r) => setFirma({ nombre: s.usuario_nombre, img: r.firma })).catch((e) => alert(e.message))
  }
  const [error, setError] = useState('')
  const admin = modo === 'admin'
  const { user } = useAuth()  // en "Todas", las salidas de equipo solo las ve TI
  const navigate = useNavigate()

  const cargar = () => {
    setError('')
    setLista([])
    if (tab === 'consultas') {
      api('/consultas', { query: { todos: true } }).then(setLista).catch((e) => setError(e.message))
      return
    }
    const query = admin ? { todos: true, estado } : { por_aprobar: true, estado }
    if (tab === 'incapacidades' || tab === 'equipos') {
      if (!query.estado) delete query.estado
      api(`/${tab}`, { query }).then(setLista).catch((e) => setError(e.message))
      return
    }
    if (tab === 'permisos' && tipo) query.tipo = tipo
    api(`/${tab}`, { query }).then(setLista).catch((e) => setError(e.message))
  }
  useEffect(cargar, [tab, estado, modo, tipo])

  // Accesos a planta negados en Teams sin motivo: hay que capturarlo aquí
  const cargarSinMotivo = () => api('/permisos/motivos-pendientes').then(setSinMotivo).catch(() => {})
  useEffect(() => { cargarSinMotivo() }, [modo])

  // Tipos de permiso de la sede (base y agregados por GH) para el filtro
  const [tiposFiltro, setTiposFiltro] = useState(null)
  useEffect(() => {
    api('/politica').then((p) => p.permisos_tipos && setTiposFiltro(p.permisos_tipos.map((t) => [t.clave, t.nombre]))).catch(() => {})
  }, [])

  // Pendientes por pestaña (círculo rojo), se actualiza al aprobar/rechazar
  const [pend, setPend] = useState({})
  useEffect(() => {
    const leer = () => api('/pendientes').then(setPend).catch(() => {})
    leer()
    window.addEventListener('pendientes:refrescar', leer)
    return () => window.removeEventListener('pendientes:refrescar', leer)
  }, [])
  // Al entrar se abre la primera pestaña que tiene algo por revisar
  const [elegida, setElegida] = useState(false)
  useEffect(() => {
    if (elegida || !Object.keys(pend).length) return
    setElegida(true)
    const k = PESTANAS.map(([t]) => t).find((t) => t !== 'consultas' && cuenta(t) > 0)
    if (k) setTab(k)
  }, [pend])
  const cuenta = (t) => ((admin ? pend[`todas_${t}`] : pend[t]) || 0) + (t === 'permisos' ? sinMotivo.length : 0)
  const marca = (t) => cuenta(t) > 0 && <span className="badge tab-badge" title={`${cuenta(t)} por revisar`}>{cuenta(t)}</span>

  async function ejecutar(ruta, body) {
    try {
      await api(ruta, { method: 'POST', body })
      setRechazo(null)
      setValidarPermiso(null)
      setValidarInc(null)
      cargar()
      cargarSinMotivo()
      window.dispatchEvent(new Event('pendientes:refrescar'))
    } catch (e) {
      alert(e.message)
    }
  }

  // Sin resultados: al ver solo lo pendiente se aclara que no hay nada por hacer
  const vacio = estado === 'solicitado' && !buscar
    ? <div className="vacio-ok"><b>No hay nada pendiente</b>Cuando alguien envíe una solicitud aparecerá aquí.</div>
    : 'No hay solicitudes con estos filtros.'
  const filtrada = agruparLotes(tab, lista).filter((s) => !buscar || (s.usuario_nombre || s.paciente_nombre)?.toLowerCase().includes(buscar.toLowerCase()))

  return (
    <div className="card">
      <div className="pestanas" role="tablist">
        {PESTANAS.filter(([k]) => (admin || k !== 'consultas') && (!admin || k !== 'equipos' || esTI(user))).map(([k, t]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'activo' : ''} onClick={() => setTab(k)}>{t}{marca(k)}</button>
        ))}
      </div>
      <div className="fila" style={{ marginBottom: 14 }}>
        {tab !== 'consultas' && (
          <select style={{ width: 180 }} value={estado} onChange={(e) => setEstado(e.target.value)}>
            <option value="">Todos los estados</option>
            {Object.entries(ESTADOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        )}
        {tab === 'permisos' && (
          <select style={{ width: 200 }} value={tipo} onChange={(e) => setTipo(e.target.value)}>
            <option value="">Todos los tipos</option>
            {(tiposFiltro || Object.entries(TIPOS_PERMISO_SOLICITABLES)).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        )}
        <input style={{ width: 220 }} placeholder="Buscar empleado…" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
      </div>
      {error && <div className="alerta error">{error}</div>}
      {sinMotivo.length > 0 && (
        <div className="alerta error">
          <b>Falta el motivo de {sinMotivo.length === 1 ? 'un acceso negado' : `${sinMotivo.length} accesos negados`} en Teams.</b>{' '}
          Teams no permite escribirlo; captúralo aquí para que caseta y GH sepan por qué no se dio el acceso.
          {sinMotivo.map((s) => (
            <div key={s.id} className="fila" style={{ marginTop: 6, gap: 8 }}>
              <span>{s.usuario_nombre} · {fmtFecha(s.fecha)} · llegó {hhmm(s.hora_fin)}</span>
              <button className="btn btn-sm" onClick={() => setRechazo({ s, motivo: '', capturar: true })}>Agregar motivo</button>
            </div>
          ))}
        </div>
      )}
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
      ) : tab === 'equipos' ? (
        <>
          <TablaSalidas lista={filtrada} vacio={vacio}
            onFormato={(s) => setFormatoEq(s)}
            acciones={(s) => s.estado === 'solicitado' && (
              <span className="fila" style={{ display: 'inline-flex', gap: 6, flexWrap: 'nowrap' }}>
                <button className="btn btn-sm btn-success" onClick={() => ejecutar(`/equipos/${s.id}/validar`)}><Check size={14} /> Autorizar</button>
                <button className="btn btn-sm btn-danger" onClick={() => setRechazo({ s, motivo: '' })}><X size={14} /> Rechazar</button>
              </span>
            )} />
          <p className="muted" style={{ fontSize: 12 }}>Formato F-630-03. Al autorizarla, TI puede revisarla (sellarla o rechazarla) antes de que el equipo salga; caseta registra la salida y el regreso.</p>
        </>
      ) : tab === 'incapacidades' ? (
        <div className="tabla-wrap">
          <table className="tabla">
            <thead><tr><th>Empleado</th><th>Fechas</th><th>Días</th><th>Tipo</th><th>Folio / observaciones</th><th>Registró</th><th>Estado</th><th /></tr></thead>
            <tbody>
              {filtrada.length === 0 && <tr><td colSpan={8} className="muted" style={{ textAlign: 'center' }}>{vacio}</td></tr>}
              {filtrada.map((i) => (
                <tr key={i.id}>
                  <td>{i.usuario_nombre}<div className="muted" style={{ fontSize: 12 }}>No. {i.usuario_numero}{i.usuario_departamento ? ` · ${i.usuario_departamento}` : ''}</div></td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {fmtFecha(i.fecha_inicio)} → {fmtFecha(i.fecha_fin)}
                    {i.fecha_inicio_original && (
                      <div className="muted" style={{ fontSize: 11 }}>Médico: {fmtFecha(i.fecha_inicio_original)} → {fmtFecha(i.fecha_fin_original)}</div>
                    )}
                  </td>
                  <td>{i.dias}{i.dias_original && i.dias_original !== i.dias && <div className="muted" style={{ fontSize: 11 }}>antes {i.dias_original}</div>}</td>
                  <td>{TIPOS_INCAPACIDAD[i.tipo] || i.tipo}</td>
                  <td className="muted">{i.folio || '—'}{i.observaciones && <div style={{ fontSize: 12 }}>{i.observaciones}</div>}</td>
                  <td className="muted">{i.medico_nombre}</td>
                  <td>
                    <span className={`pill ${i.estado}`}>{ESTADOS_INCAPACIDAD[i.estado] || ESTADOS[i.estado]}</span>
                    {i.estado !== 'solicitado' && i.revisado_por_nombre && <div className="muted" style={{ fontSize: 11 }}>{i.revisado_por_nombre}</div>}
                    {i.estado === 'solicitado' && <div className="muted" style={{ fontSize: 11 }}>Valida: {i.aprobador_nombre || 'GH'}</div>}
                    {i.motivo_rechazo && <div style={{ fontSize: 11, color: 'var(--danger)' }}>{i.motivo_rechazo}</div>}
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {i.estado === 'solicitado' && (
                      <div className="fila" style={{ flexWrap: 'nowrap' }}>
                        <button className="btn btn-sm btn-success"
                          onClick={() => setValidarInc({ i, fecha_inicio: i.fecha_inicio, fecha_fin: i.fecha_fin, comentario: '' })}>
                          <Check size={14} /> Validar
                        </button>
                        <button className="btn btn-sm btn-danger" onClick={() => setRechazo({ s: i, motivo: '' })}><X size={14} /> Rechazar</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 12 }}>Las incapacidades las genera el servicio médico en la consulta. Aquí no se muestra información clínica. Al validarlas o rechazarlas se notifica por correo a GH.</p>
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
            {filtrada.length === 0 && <tr><td colSpan={7} className="muted" style={{ textAlign: 'center' }}>{vacio}</td></tr>}
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
                    <td>{nombreTipo(s)}</td>
                    <td>
                      {s.dias_lote ? (
                        <>
                          <b>{s.dias_lote.length} días</b> <span className="chip" title="Se aprueban o rechazan todos juntos">una sola aprobación</span>
                          <div className="muted" style={{ fontSize: 12 }}>{s.dias_lote.map((f) => fmtFecha(f)).join(', ')}</div>
                        </>
                      ) : <>{fmtFecha(s.fecha)}{s.por_dias && s.fecha_fin && s.fecha_fin !== s.fecha ? ` → ${fmtFecha(s.fecha_fin)}` : ''}</>}
                    </td>
                    <td>{s.por_dias
                      ? <span className="muted">{s.dias ?? '—'} día(s) laborales</span>
                      : <>{hhmm(s.hora_inicio)} - {hhmm(s.hora_fin)} <span className="muted">({num(s.horas)} h)</span></>}</td>
                    <td className="muted">
                      {s.registrado_por_nombre && <span className="chip" style={{ marginRight: 4 }}>Caseta: {s.registrado_por_nombre}</span>}
                      {s.motivo}
                      {s.tipo_nomina && <div style={{ fontSize: 11 }}>{TIPOS_NOMINA[s.tipo_nomina]}{s.departamento && ` · ${s.departamento}`}</div>}
                    </td>
                  </>
                )}
                <td>
                  <span className={`pill ${s.estado}`}>{s.falta_gh ? 'Aprobada por el jefe' : ESTADOS[s.estado]}</span>
                  {s.estado === 'rechazado' && (s.motivo_rechazo_pendiente
                    ? <div style={{ fontSize: 11, color: 'var(--danger)' }}>Falta el motivo</div>
                    : s.motivo_rechazo && <div className="muted" style={{ fontSize: 11 }}>{s.motivo_rechazo}</div>)}
                  {s.falta_gh && <div className="muted" style={{ fontSize: 11 }}>{s.aprobado_jefe_nombre} · falta GH</div>}
                  {s.paso_actual && <div className="muted" style={{ fontSize: 11 }}>Paso actual: {s.paso_actual}</div>}
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
      {formatoEq && <FormatoEquipo salida={formatoEq} onClose={() => setFormatoEq(null)} />}
      {verConsulta && <DetalleConsulta consultaId={verConsulta} onClose={() => setVerConsulta(null)} />}
      {firma && (
        <Modal titulo={`Firma de ${firma.nombre}`} onClose={() => setFirma(null)}
          pie={<button className="btn" onClick={() => setFirma(null)}>Cerrar</button>}>
          {firma.img ? <img className="firma-img" style={{ height: 140 }} src={firma.img} alt="Firma" /> : 'Sin firma'}
        </Modal>
      )}
      {rechazo && (() => {
        // Negar el acceso a planta por retardo (caseta) exige el motivo
        const acceso = rechazo.capturar || (tab === 'permisos' && rechazo.s.tipo === 'llegada_tarde')
        const minimo = acceso ? 5 : tab === 'equipos' ? 3 : tab === 'incapacidades' ? 1 : 0
        const falta = rechazo.motivo.trim().length < minimo
        const ruta = rechazo.capturar ? `/permisos/${rechazo.s.id}/motivo-rechazo` : `/${tab}/${rechazo.s.id}/rechazar`
        return (
          <Modal titulo={rechazo.capturar ? 'Motivo del acceso negado' : acceso ? 'Negar acceso a planta'
            : tab === 'incapacidades' ? 'Rechazar incapacidad' : tab === 'equipos' ? 'Rechazar salida de equipo' : 'Rechazar solicitud'} onClose={() => setRechazo(null)}
            pie={<>
              <button className="btn" onClick={() => setRechazo(null)}>Cancelar</button>
              <button className="btn btn-danger" disabled={falta}
                onClick={() => ejecutar(ruta, { motivo: rechazo.motivo })}>{rechazo.capturar ? 'Guardar motivo' : acceso ? 'Negar acceso' : 'Rechazar'}</button>
            </>}>
            <p>{acceso ? 'Acceso a planta por retardo' : tab === 'incapacidades' ? 'Incapacidad' : 'Solicitud'} de <b>{rechazo.s.usuario_nombre}</b>
              {acceso && <span className="muted"> · {fmtFecha(rechazo.s.fecha)}, llegó {hhmm(rechazo.s.hora_fin)}. Caseta verá el motivo.</span>}
              {tab === 'incapacidades' && !acceso && <span className="muted"> · {fmtFecha(rechazo.s.fecha_inicio)} → {fmtFecha(rechazo.s.fecha_fin)} ({rechazo.s.dias} día(s)). Se notificará a GH y quedará en la bitácora del servicio médico.</span>}
            </p>
            <label className="campo">{acceso ? 'Motivo por el que no se da el acceso (obligatorio)' : 'Motivo del rechazo'}
              <textarea rows={3} maxLength={500} autoFocus={acceso} value={rechazo.motivo}
                onChange={(e) => setRechazo({ ...rechazo, motivo: e.target.value })} />
            </label>
            {acceso && falta && <p className="muted" style={{ fontSize: 12 }}>Escribe al menos 5 caracteres.</p>}
          </Modal>
        )
      })()}
      {validarInc && (() => {
        const v = validarInc
        const dias = v.fecha_inicio && v.fecha_fin && v.fecha_fin >= v.fecha_inicio
          ? Math.round((new Date(v.fecha_fin) - new Date(v.fecha_inicio)) / 864e5) + 1 : 0
        const cambio = v.fecha_inicio !== v.i.fecha_inicio || v.fecha_fin !== v.i.fecha_fin
        return (
          <Modal titulo="Validar incapacidad" onClose={() => setValidarInc(null)}
            pie={<>
              <button className="btn" onClick={() => setValidarInc(null)}>Cancelar</button>
              <button className="btn btn-danger" onClick={() => { setValidarInc(null); setRechazo({ s: v.i, motivo: '' }) }}>
                <X size={14} /> Rechazar
              </button>
              <button className="btn btn-success" disabled={!dias}
                onClick={() => ejecutar(`/incapacidades/${v.i.id}/validar`, {
                  fecha_inicio: cambio ? v.fecha_inicio : null, fecha_fin: cambio ? v.fecha_fin : null, comentario: v.comentario.trim() || null,
                })}>
                <Check size={14} /> {cambio ? `Validar con ${dias} día(s)` : 'Validar'}
              </button>
            </>}>
            <p style={{ marginTop: 0 }}>
              <b>{v.i.usuario_nombre}</b> · {TIPOS_INCAPACIDAD[v.i.tipo] || v.i.tipo}{v.i.folio ? ` · Folio ${v.i.folio}` : ''}<br />
              <span className="muted">El servicio médico registró {fmtFecha(v.i.fecha_inicio)} → {fmtFecha(v.i.fecha_fin)} ({v.i.dias} día(s)). Puedes ajustar los días antes de validarla.</span>
            </p>
            <div className="form-grid">
              <label className="campo">Desde
                <input type="date" value={v.fecha_inicio}
                  onChange={(e) => setValidarInc({ ...v, fecha_inicio: e.target.value, fecha_fin: v.fecha_fin < e.target.value ? e.target.value : v.fecha_fin })} />
              </label>
              <label className="campo">Hasta
                <input type="date" value={v.fecha_fin} min={v.fecha_inicio} onChange={(e) => setValidarInc({ ...v, fecha_fin: e.target.value })} />
              </label>
              <div className="full fila" style={{ gap: 8 }}>
                <b>{dias} día(s) naturales</b>
                {cambio && <span className="pill solicitado">Ajustada: antes {v.i.dias} día(s)</span>}
                {cambio && (
                  <button type="button" className="btn btn-sm" onClick={() => setValidarInc({ ...v, fecha_inicio: v.i.fecha_inicio, fecha_fin: v.i.fecha_fin })}>
                    Restaurar fechas del médico
                  </button>
                )}
              </div>
              <label className="campo full">Comentario {cambio ? '(recomendado: por qué se ajustan los días)' : '(opcional)'}
                <textarea rows={2} maxLength={500} value={v.comentario} onChange={(e) => setValidarInc({ ...v, comentario: e.target.value })} />
              </label>
            </div>
            <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
              Los días validados quedan en el calendario del colaborador y se notifica a GH, incluidas las fechas originales si las cambias.
            </p>
          </Modal>
        )
      })()}
      {validarPermiso && (
        <Modal titulo="Validar permiso" onClose={() => setValidarPermiso(null)}
          pie={<>
            <button className="btn" onClick={() => setValidarPermiso(null)}>Cancelar</button>
            <button className="btn btn-success" disabled={!!validarPermiso.registrado_por_nombre && !validarPermiso.tipo_nomina && !validarPermiso.nomina}
              onClick={() => ejecutar(`/permisos/${validarPermiso.id}/validar`, {
                observaciones: validarPermiso.obs || null, tipo_nomina: validarPermiso.nomina || null,
              })}>Validar</button>
          </>}>
          <p><b>{validarPermiso.usuario_nombre}</b> · {nombreTipo(validarPermiso)} · {validarPermiso.dias_lote
            ? `${validarPermiso.dias_lote.length} días (${validarPermiso.dias_lote.map((f) => fmtFecha(f)).join(', ')})`
            : fmtFecha(validarPermiso.fecha)} {hhmm(validarPermiso.hora_inicio)}-{hhmm(validarPermiso.hora_fin)}</p>
          {validarPermiso.dias_lote && <p className="muted" style={{ marginTop: -6, fontSize: 13 }}>Se validan todos los días juntos.</p>}
          {validarPermiso.registrado_por_nombre && (
            <div className="alerta warn" style={{ margin: '0 0 10px' }}>
              Retardo registrado en caseta por <b>{validarPermiso.registrado_por_nombre}</b>: el empleado no lo solicitó ni lo firmó.
            </div>
          )}
          {validarPermiso.registrado_por_nombre && !validarPermiso.tipo_nomina && (
            <label className="campo" style={{ marginBottom: 10 }}>Cómo se considera el tiempo en nómina *
              <select value={validarPermiso.nomina || ''} onChange={(e) => setValidarPermiso({ ...validarPermiso, nomina: e.target.value })}>
                <option value="">Selecciona…</option>
                {Object.entries(TIPOS_NOMINA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
          )}
          <label className="campo">
            {validarPermiso.tipo === 'consulta_medica' ? 'Observaciones del médico de planta (opcional)' : 'Observaciones (opcional)'}
            <textarea rows={3} value={validarPermiso.obs || ''} onChange={(e) => setValidarPermiso({ ...validarPermiso, obs: e.target.value })} />
          </label>
        </Modal>
      )}
    </div>
  )
}

/** Junta en una fila los días de un permiso pedido para varios días (mismo lote y mismo punto de aprobación). */
function agruparLotes(tab, lista) {
  if (tab !== 'permisos') return lista
  const grupos = new Map()
  const res = []
  for (const s of lista) {
    if (!s.lote) { res.push(s); continue }
    const k = `${s.lote}|${s.estado}|${s.paso_actual || ''}|${s.falta_gh ? 1 : 0}`
    const g = grupos.get(k)
    if (!g) {
      const fila = { ...s, dias_lote: [s.fecha], ids_lote: [s.id] }
      grupos.set(k, fila)
      res.push(fila)
    } else {
      g.dias_lote.push(s.fecha)
      g.ids_lote.push(s.id)
      if (s.id === s.lote) Object.assign(g, { ...s, dias_lote: g.dias_lote, ids_lote: g.ids_lote })  // el principal representa al lote
    }
  }
  for (const g of grupos.values()) {
    g.dias_lote.sort()
    if (g.dias_lote.length < 2) delete g.dias_lote
  }
  return res
}
