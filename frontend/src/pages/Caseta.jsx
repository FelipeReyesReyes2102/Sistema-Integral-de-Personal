import { useEffect, useRef, useState } from 'react'
import { AlarmClock, Ban, CheckCircle2, DoorOpen, Footprints, Hourglass, Laptop, MessageSquare, RefreshCw, Search, Send, X, XCircle } from 'lucide-react'
import { api } from '../api'
import Avatar from '../components/Avatar'
import BuscadorPaciente from '../components/BuscadorPaciente'
import { CATEGORIAS, fmtFecha } from '../utils'

const ahoraHHMM = () => new Date().toTimeString().slice(0, 5)
const minutos = (a, b) => {
  if (!a || !b) return 0
  const [h1, m1] = a.split(':').map(Number)
  const [h2, m2] = b.split(':').map(Number)
  return h2 * 60 + m2 - (h1 * 60 + m1)
}

/** Qué debe esperar caseta de cada permiso por horas. */
function Movimiento({ p }) {
  if (p.tipo === 'llegada_tarde') return <><AlarmClock size={14} /> Entra a las <b>{p.hora_fin}</b> <span className="muted">(su entrada es {p.hora_inicio})</span></>
  if (p.tipo === 'salida_temprana') return <><DoorOpen size={14} /> Sale a las <b>{p.hora_inicio}</b> y ya no regresa</>
  if (p.tipo === 'salida_intermedia') return <><Footprints size={14} /> Sale a las <b>{p.hora_inicio}</b> y regresa a las <b>{p.hora_fin}</b></>
  return <>De <b>{p.hora_inicio}</b> a <b>{p.hora_fin}</b></>
}

function PermisosHoy({ onSolicitar, pendientesIds = [] }) {
  const [datos, setDatos] = useState(null)
  const [buscar, setBuscar] = useState('')
  const [error, setError] = useState('')
  const cargar = () => api('/caseta/hoy').then((d) => { setDatos(d); setError('') }).catch((e) => setError(e.message))
  useEffect(() => {
    cargar()
    const t = setInterval(cargar, 60000) // se actualiza solo cada minuto
    return () => clearInterval(t)
  }, [])
  // Búsqueda entre todo el personal de la sede (sin acentos, por palabras), con sus permisos del día
  const [personas, setPersonas] = useState(null)
  const [buscando, setBuscando] = useState(false)
  useEffect(() => {
    if (!buscar.trim()) { setPersonas(null); return undefined }
    setBuscando(true)
    const t = setTimeout(() => {
      api('/caseta/empleados', { query: { q: buscar, con_permisos: true, limite: 20 } })
        .then(setPersonas).catch((e) => setError(e.message)).finally(() => setBuscando(false))
    }, 250)
    return () => clearTimeout(t)
  }, [buscar])
  const enBusqueda = buscar.trim().length > 0
  const horas = enBusqueda ? [] : datos?.por_horas || []
  const dias = enBusqueda ? [] : datos?.por_dias || []

  return (
    <div className="card">
      <div className="fila" style={{ marginBottom: 12 }}>
        <div>
          <b style={{ fontSize: 16 }}>Permisos validados · {datos ? fmtFecha(datos.fecha) : '…'}</b>
          <div className="muted" style={{ fontSize: 12 }}>Hora local {datos?.hora_local || '—'} · se actualiza cada minuto</div>
        </div>
        <div className="espacio" />
        <div className="bp-input" style={{ width: 260 }}>
          <Search size={16} />
          <input value={buscar} onChange={(e) => setBuscar(e.target.value)} placeholder="Buscar a cualquier persona (nombre o nómina)" />
          {buscar && <button type="button" className="icon-btn plain" title="Limpiar" onClick={() => setBuscar('')}><X size={14} /></button>}
        </div>
        <button className="btn btn-sm" onClick={cargar}><RefreshCw size={14} /> Actualizar</button>
      </div>
      {error && <div className="alerta error">{error}</div>}
      {enBusqueda && (
        <div className="caseta-lista">
          {buscando && !personas && <div className="muted" style={{ padding: 16, textAlign: 'center' }}>Buscando…</div>}
          {personas && personas.length === 0 && (
            <div className="muted" style={{ padding: 16, textAlign: 'center' }}>No se encontró a nadie con "{buscar}". Prueba con un apellido o el número de nómina.</div>
          )}
          {(personas || []).map((e) => (
            <div key={e.id} className="caseta-item" style={{ borderLeftColor: e.permisos_hoy.some((x) => x.estado === 'validado') ? '#2e7d32' : '#c3cad6' }}>
              <Avatar usuario={{ id: e.id, nombre: e.nombre, tiene_foto: e.tiene_foto }} tam={40} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="caseta-nombre">{e.nombre}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  No. {e.numero_empleado}{e.departamento ? ` · ${e.departamento}` : ''}{e.turno ? ` · ${e.turno}` : ''}
                  {e.entrada_hoy ? ` · hoy ${e.entrada_hoy}–${e.salida_hoy}` : ' · sin turno'}{e.jefe_nombre ? ` · Jefe: ${e.jefe_nombre}` : ''}
                </div>
                {e.permisos_hoy.length === 0 && <div className="caseta-mov muted">Sin permisos hoy</div>}
                {e.permisos_hoy.map((p) => (
                  <div key={p.id} className="caseta-mov">
                    <span className={`pill ${p.estado}`}>{p.estado === 'validado' ? 'Autorizado' : 'Pendiente'}</span>
                    <b>{p.tipo_nombre}</b>
                    {p.por_dias ? <span>todo el día ({fmtFecha(p.fecha)} → {fmtFecha(p.fecha_fin)})</span> : <Movimiento p={p} />}
                  </div>
                ))}
              </div>
              <div>
                {pendientesIds.includes(e.id)
                  ? <span className="muted" style={{ fontSize: 12 }}>Ya tiene solicitud de ingreso hoy</span>
                  : (
                    <button className="btn btn-sm btn-primary" disabled={!e.entrada_hoy} title={e.entrada_hoy ? 'Pedir a su jefe que autorice su ingreso' : 'No tiene turno asignado'}
                      onClick={() => onSolicitar(e)}>
                      <Send size={14} /> Solicitar ingreso
                    </button>
                  )}
              </div>
            </div>
          ))}
        </div>
      )}
      {!enBusqueda && datos && horas.length === 0 && dias.length === 0 && (
        <div className="muted" style={{ padding: 24, textAlign: 'center' }}>No hay permisos validados para hoy.</div>
      )}
      <div className="caseta-lista">
        {horas.map((p) => (
          <div key={p.id} className="caseta-item" style={{ borderLeftColor: CATEGORIAS[p.categoria]?.color || '#888' }}>
            <Avatar usuario={{ id: p.usuario_id, nombre: p.nombre, tiene_foto: p.tiene_foto }} tam={40} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="caseta-nombre">{p.nombre}</div>
              <div className="muted" style={{ fontSize: 12 }}>No. {p.numero_empleado}{p.departamento ? ` · ${p.departamento}` : ''}{p.turno ? ` · ${p.turno}` : ''}</div>
              <div className="caseta-mov"><Movimiento p={p} /></div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <span className="pill validado">{p.tipo_nombre}</span>
              <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>Autorizó: {p.autorizo || '—'}</div>
              {p.registrado_por && <div className="muted" style={{ fontSize: 11 }}>Retardo de caseta</div>}
            </div>
          </div>
        ))}
      </div>
      {dias.length > 0 && (
        <>
          <h4 className="fila" style={{ gap: 6, margin: '18px 0 8px', fontSize: 14 }}><Laptop size={16} /> Fuera de planta todo el día</h4>
          <div className="caseta-lista">
            {dias.map((p) => (
              <div key={p.id} className="caseta-item compacto" style={{ borderLeftColor: CATEGORIAS[p.categoria]?.color || '#888' }}>
                <Avatar usuario={{ id: p.usuario_id, nombre: p.nombre, tiene_foto: p.tiene_foto }} tam={32} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="caseta-nombre">{p.nombre}</div>
                  <div className="muted" style={{ fontSize: 12 }}>No. {p.numero_empleado} · {p.tipo_nombre} · {fmtFecha(p.fecha)} → {fmtFecha(p.fecha_fin)}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// Estado de la solicitud de acceso a planta, tal como lo necesita caseta
function Acceso({ r }) {
  if (r.estado === 'validado') {
    return <div className="acceso ok"><CheckCircle2 size={18} /> <b>ACCESO AUTORIZADO</b><span>{r.autorizo}{r.observaciones ? ` · "${r.observaciones}"` : ''}</span></div>
  }
  if (r.estado === 'rechazado') {
    return <div className="acceso no"><XCircle size={18} /> <b>ACCESO DENEGADO</b><span>{r.autorizo}{r.motivo_rechazo ? ` · ${r.motivo_rechazo}` : ''}</span></div>
  }
  if (r.estado === 'cancelado') return <div className="acceso cancelado"><Ban size={18} /> <b>Cancelado</b></div>
  return (
    <div className="acceso espera">
      <Hourglass size={18} /> <b>Esperando autorización</b>
      <span>de {r.va_a_gh ? `GH (${r.aprobador_nombre || 'Gestión Humana'})` : r.aprobador_nombre}
        {r.teams ? (r.teams.estado === 'enviado' ? ' · enviada a Teams' : r.teams.estado === 'error' ? ' · error al enviar a Teams' : ' · enviando a Teams…')
          : ' · en SIP-O y por correo'}</span>
    </div>
  )
}

const espera = (iso) => {
  if (!iso) return ''
  const m = Math.max(0, Math.round((Date.now() - new Date(`${iso.slice(0, 19)}`).getTime()) / 60000))
  return m < 1 ? 'hace un momento' : `hace ${m} min`
}

/** Solicitudes de ingreso esperando la autorización del jefe: salen de aquí en cuanto responde. */
function Pendientes({ lista, onCancelar }) {
  const pend = lista.filter((r) => r.estado === 'solicitado')
  if (!pend.length) return null
  return (
    <div className="card pendientes-ingreso">
      <div className="fila" style={{ marginBottom: 8 }}>
        <Hourglass size={18} /> <b style={{ fontSize: 15 }}>Esperando autorización de ingreso ({pend.length})</b>
        <div className="espacio" />
        <span className="muted" style={{ fontSize: 12 }}>Salen de esta lista cuando el jefe responde</span>
      </div>
      <div className="caseta-lista">
        {pend.map((r) => (
          <div key={r.id} className="caseta-item" style={{ borderLeftColor: '#e0a100' }}>
            <Avatar usuario={{ id: r.usuario_id, nombre: r.nombre, tiene_foto: r.tiene_foto }} tam={40} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="caseta-nombre">{r.nombre}</div>
              <div className="muted" style={{ fontSize: 12 }}>
                No. {r.numero_empleado}{r.departamento ? ` · ${r.departamento}` : ''} · llegó {r.hora_fin} (entrada {r.hora_inicio}, {minutos(r.hora_inicio, r.hora_fin)} min)
              </div>
              <Acceso r={r} />
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="muted" style={{ fontSize: 12 }}>Solicitado {espera(r.creado)}</div>
              <button className="btn btn-sm" style={{ marginTop: 6 }} title="Registro equivocado" onClick={() => onCancelar(r)}><Ban size={14} /> Cancelar</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Retardos({ lista, inicial, onRegistrado }) {
  const [emp, setEmp] = useState(inicial || null)
  const [hora, setHora] = useState(ahoraHHMM())
  const [motivo, setMotivo] = useState('')
  const [gh, setGh] = useState(false)
  const [msg, setMsg] = useState(null)
  const [enviando, setEnviando] = useState(false)
  useEffect(() => { if (inicial) setEmp(inicial) }, [inicial])
  useEffect(() => { setHora(ahoraHHMM()); setGh(false) }, [emp?.id])

  const retraso = emp?.entrada_hoy ? minutos(emp.entrada_hoy, hora) : 0
  const destino = !emp ? '' : gh || !emp.jefe_nombre ? 'Gestión Humana (GH)' : emp.jefe_nombre
  const yaPendiente = emp && lista.some((r) => r.usuario_id === emp.id && ['solicitado', 'validado'].includes(r.estado))
  const resueltos = lista.filter((r) => r.estado !== 'solicitado')

  async function registrar() {
    setMsg(null)
    setEnviando(true)
    try {
      const r = await api('/caseta/retardos', { method: 'POST', body: { usuario_id: emp.id, hora_llegada: hora, motivo: motivo.trim() || null, enviar_gh: gh } })
      setMsg({ ok: true, t: `Solicitud de ingreso de ${r.nombre} enviada a ${r.va_a_gh ? `GH (${r.aprobador_nombre || 'Gestión Humana'})` : r.aprobador_nombre}${r.teams ? ' en SIP-O y Teams' : ''}. Queda en "Esperando autorización" hasta que responda.` })
      setEmp(null)
      setMotivo('')
      onRegistrado()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setEnviando(false)
    }
  }

  return (
    <>
      <div className="card">
        <b style={{ fontSize: 16 }}>Solicitar ingreso a planta (retardo)</b>
        <p className="muted" style={{ marginTop: 4, fontSize: 13 }}>
          Selecciona a la persona que llegó después de su hora de entrada y envía la solicitud a su <b>jefe inmediato</b> (en SIP-O y en
          <b> Teams</b>). Si no tiene jefe o el jefe no está en planta, se pide a GH. Queda como permiso de llegada tarde.
        </p>
        <BuscadorPaciente value={emp} onChange={setEmp} endpoint="/caseta/empleados"
          placeholder="Nombre, apellido o número de nómina…"
          extra={(p) => [p.entrada_hoy ? `Entrada hoy ${p.entrada_hoy}` : 'Sin turno', p.jefe_nombre ? `Jefe: ${p.jefe_nombre}` : 'Sin jefe (GH)'].join(' · ')} />
        {emp && (
          <div className="form-grid" style={{ marginTop: 12 }}>
            {yaPendiente && <div className="full alerta warn" style={{ margin: 0 }}>{emp.nombre} ya tiene una solicitud de ingreso hoy (pendiente o autorizada).</div>}
            <label className="campo">Hora de llegada
              <input type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
              <span className="muted" style={{ fontSize: 11 }}>
                {emp.entrada_hoy ? (retraso > 0 ? `Entrada ${emp.entrada_hoy} · ${retraso} min de retardo` : `Su entrada es ${emp.entrada_hoy}: no es retardo`) : 'No tiene turno asignado'}
              </span>
            </label>
            <label className="campo">Motivo (opcional)
              <input value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={500} placeholder="Ej. tráfico, transporte" />
            </label>
            <label className="checkbox full">
              <input type="checkbox" checked={gh} onChange={(e) => setGh(e.target.checked)} disabled={!emp.jefe_nombre} />
              El jefe inmediato no está en planta: enviar a GH
            </label>
            <div className="full fila">
              <span className="muted">Se enviará a: <b>{destino}</b></span>
              <div className="espacio" />
              <button className="btn btn-primary" onClick={registrar} disabled={enviando || !emp.entrada_hoy || retraso <= 0 || yaPendiente}>
                <Send size={15} /> {enviando ? 'Enviando…' : 'Enviar solicitud de ingreso'}
              </button>
            </div>
          </div>
        )}
        {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`} style={{ marginTop: 12 }}>{msg.t}</div>}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <b>Resueltas hoy</b>
        <div className="tabla-wrap" style={{ marginTop: 10 }}>
          <table className="tabla">
            <thead><tr><th>Empleado</th><th>Entrada</th><th>Llegó</th><th>Ingreso a planta</th></tr></thead>
            <tbody>
              {resueltos.length === 0 && <tr><td colSpan={4} className="muted" style={{ textAlign: 'center' }}>Aún no hay solicitudes resueltas hoy.</td></tr>}
              {resueltos.map((r) => (
                <tr key={r.id}>
                  <td>{r.nombre}<div className="muted" style={{ fontSize: 12 }}>No. {r.numero_empleado}{r.departamento ? ` · ${r.departamento}` : ''}</div></td>
                  <td>{r.hora_inicio}</td>
                  <td><b>{r.hora_fin}</b> <span className="muted">({minutos(r.hora_inicio, r.hora_fin)} min)</span></td>
                  <td><Acceso r={r} />{r.teams?.nota && <div className="muted" style={{ fontSize: 11 }}><MessageSquare size={11} /> {r.teams.nota}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

/** Caseta: permisos validados del día y solicitudes de ingreso por retardo. */
export default function Caseta() {
  const [tab, setTab] = useState('hoy')
  const [seleccion, setSeleccion] = useState(null)
  const [lista, setLista] = useState([])
  const [aviso, setAviso] = useState(null)
  const previos = useRef({})

  // Cada 15 s (en las dos pestañas): el jefe puede responder en SIP-O o en Teams y caseta lo ve casi al momento
  const cargar = () => api('/caseta/retardos').then((l) => {
    const cambios = l.filter((r) => previos.current[r.id] === 'solicitado' && ['validado', 'rechazado'].includes(r.estado))
    if (cambios.length) {
      const c = cambios[0]
      setAviso({ ok: c.estado === 'validado', t: `${c.nombre}: ingreso ${c.estado === 'validado' ? 'AUTORIZADO' : 'DENEGADO'} por ${c.autorizo || 'su jefe'}${c.estado === 'rechazado' && c.motivo_rechazo ? ` (${c.motivo_rechazo})` : ''}.` })
    }
    previos.current = Object.fromEntries(l.map((r) => [r.id, r.estado]))
    setLista(l)
  }).catch(() => {})
  useEffect(() => {
    cargar()
    const t = setInterval(cargar, 15000)
    return () => clearInterval(t)
  }, [])

  async function cancelar(r) {
    if (!window.confirm(`¿Cancelar la solicitud de ingreso de ${r.nombre}?`)) return
    try {
      await api(`/caseta/retardos/${r.id}/cancelar`, { method: 'POST' })
      cargar()
    } catch (e) {
      alert(e.message)
    }
  }

  const solicitar = (persona) => { setSeleccion({ ...persona }); setTab('retardos') }
  const pendientes = lista.filter((r) => r.estado === 'solicitado').length

  return (
    <>
      <div className="tabs" style={{ marginBottom: 12 }}>
        <button className={tab === 'hoy' ? 'activo' : ''} onClick={() => setTab('hoy')}>PERMISOS DE HOY</button>
        <button className={tab === 'retardos' ? 'activo' : ''} onClick={() => setTab('retardos')}>
          INGRESO POR RETARDO{pendientes > 0 && <span className="badge tab-badge" title={`${pendientes} esperando autorización`}>{pendientes}</span>}
        </button>
      </div>
      {aviso && (
        <div className={`alerta ${aviso.ok ? 'ok' : 'error'} acceso-aviso`} role="alert" onClick={() => setAviso(null)} style={{ marginTop: 0, marginBottom: 12 }}>
          {aviso.ok ? <CheckCircle2 size={18} /> : <XCircle size={18} />} {aviso.t} <span className="muted">(clic para cerrar)</span>
        </div>
      )}
      <Pendientes lista={lista} onCancelar={cancelar} />
      {tab === 'hoy'
        ? <PermisosHoy onSolicitar={solicitar} pendientesIds={lista.filter((r) => ['solicitado', 'validado'].includes(r.estado)).map((r) => r.usuario_id)} />
        : <Retardos lista={lista} inicial={seleccion} onRegistrado={cargar} />}
    </>
  )
}
