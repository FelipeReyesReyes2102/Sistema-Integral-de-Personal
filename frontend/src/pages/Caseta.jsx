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

function PermisosHoy() {
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

function Retardos() {
  const [emp, setEmp] = useState(null)
  const [hora, setHora] = useState(ahoraHHMM())
  const [motivo, setMotivo] = useState('')
  const [gh, setGh] = useState(false)
  const [lista, setLista] = useState([])
  const [msg, setMsg] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [aviso, setAviso] = useState(null)
  const previos = useRef({})
  // Se consulta cada 15 s: el jefe puede responder en SIP-O o en Teams y caseta lo ve casi al momento
  const cargar = () => api('/caseta/retardos').then((l) => {
    const cambios = l.filter((r) => previos.current[r.id] === 'solicitado' && r.estado !== 'solicitado' && r.estado !== 'cancelado')
    if (cambios.length) {
      const c = cambios[0]
      setAviso({ ok: c.estado === 'validado', t: `${c.nombre}: ${c.estado === 'validado' ? 'acceso AUTORIZADO' : 'acceso DENEGADO'} por ${c.autorizo || 'su jefe'}.` })
    }
    previos.current = Object.fromEntries(l.map((r) => [r.id, r.estado]))
    setLista(l)
  }).catch(() => {})
  useEffect(() => {
    cargar()
    const t = setInterval(cargar, 15000)
    return () => clearInterval(t)
  }, [])
  const esperando = lista.filter((r) => r.estado === 'solicitado').length
  useEffect(() => { setHora(ahoraHHMM()); setGh(false) }, [emp?.id])

  const retraso = emp?.entrada_hoy ? minutos(emp.entrada_hoy, hora) : 0
  const destino = !emp ? '' : gh || !emp.jefe_nombre ? 'Gestión Humana (GH)' : emp.jefe_nombre

  async function registrar() {
    setMsg(null)
    setEnviando(true)
    try {
      const r = await api('/caseta/retardos', { method: 'POST', body: { usuario_id: emp.id, hora_llegada: hora, motivo: motivo.trim() || null, enviar_gh: gh } })
      setMsg({ ok: true, t: `Solicitud de acceso de ${r.nombre} enviada a ${r.va_a_gh ? `GH (${r.aprobador_nombre || 'Gestión Humana'})` : r.aprobador_nombre}${r.teams ? ' en SIP-O y Teams' : ''}. Su respuesta aparecerá abajo.` })
      setEmp(null)
      setMotivo('')
      cargar()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setEnviando(false)
    }
  }

  async function cancelar(r) {
    if (!window.confirm(`¿Cancelar el retardo de ${r.nombre}?`)) return
    try {
      await api(`/caseta/retardos/${r.id}/cancelar`, { method: 'POST' })
      cargar()
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <>
      <div className="card">
        <b style={{ fontSize: 16 }}>Retardo: solicitar acceso a planta</b>
        <p className="muted" style={{ marginTop: 4, fontSize: 13 }}>
          Si alguien llega después de su hora de entrada, regístralo aquí: se pide a su <b>jefe inmediato</b> que autorice el acceso a
          planta, en SIP-O y en <b>Teams</b>. Si no tiene jefe o el jefe no está en planta, se pide a GH. Queda como permiso de llegada tarde.
        </p>
        <BuscadorPaciente value={emp} onChange={setEmp} endpoint="/caseta/empleados"
          placeholder="Nombre, apellido o número de nómina…"
          extra={(p) => [p.entrada_hoy ? `Entrada hoy ${p.entrada_hoy}` : 'Sin turno', p.jefe_nombre ? `Jefe: ${p.jefe_nombre}` : 'Sin jefe (GH)'].join(' · ')} />
        {emp && (
          <div className="form-grid" style={{ marginTop: 12 }}>
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
              <button className="btn btn-primary" onClick={registrar} disabled={enviando || !emp.entrada_hoy || retraso <= 0}>
                <Send size={15} /> {enviando ? 'Enviando…' : 'Solicitar acceso'}
              </button>
            </div>
          </div>
        )}
        {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`} style={{ marginTop: 12 }}>{msg.t}</div>}
      </div>
      {aviso && (
        <div className={`alerta ${aviso.ok ? 'ok' : 'error'} acceso-aviso`} role="alert" onClick={() => setAviso(null)}>
          {aviso.ok ? <CheckCircle2 size={18} /> : <XCircle size={18} />} {aviso.t} <span className="muted">(clic para cerrar)</span>
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <div className="fila">
          <b>Retardos de hoy</b>
          {esperando > 0 && <span className="pill solicitado">{esperando} esperando autorización</span>}
          <div className="espacio" />
          <span className="muted" style={{ fontSize: 12 }}>Se actualiza cada 15 s</span>
          <button className="btn btn-sm" onClick={cargar}><RefreshCw size={14} /> Actualizar</button>
        </div>
        <div className="tabla-wrap" style={{ marginTop: 10 }}>
          <table className="tabla">
            <thead><tr><th>Empleado</th><th>Entrada</th><th>Llegó</th><th>Acceso a planta</th><th /></tr></thead>
            <tbody>
              {lista.length === 0 && <tr><td colSpan={5} className="muted" style={{ textAlign: 'center' }}>Sin retardos registrados hoy.</td></tr>}
              {lista.map((r) => (
                <tr key={r.id}>
                  <td>{r.nombre}<div className="muted" style={{ fontSize: 12 }}>No. {r.numero_empleado}{r.departamento ? ` · ${r.departamento}` : ''}</div></td>
                  <td>{r.hora_inicio}</td>
                  <td><b>{r.hora_fin}</b> <span className="muted">({minutos(r.hora_inicio, r.hora_fin)} min)</span></td>
                  <td><Acceso r={r} />{r.teams?.nota && r.estado === 'solicitado' && <div className="muted" style={{ fontSize: 11 }}><MessageSquare size={11} /> {r.teams.nota}</div>}</td>
                  <td>{r.estado === 'solicitado' && (
                    <button className="icon-btn rojo" title="Cancelar (registro equivocado)" onClick={() => cancelar(r)}><Ban size={16} /></button>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

/** Caseta: permisos validados del día y registro de retardos. */
export default function Caseta() {
  const [tab, setTab] = useState('hoy')
  return (
    <>
      <div className="tabs" style={{ marginBottom: 12 }}>
        <button className={tab === 'hoy' ? 'activo' : ''} onClick={() => setTab('hoy')}>PERMISOS DE HOY</button>
        <button className={tab === 'retardos' ? 'activo' : ''} onClick={() => setTab('retardos')}>RETARDOS</button>
      </div>
      {tab === 'hoy' ? <PermisosHoy /> : <Retardos />}
    </>
  )
}
