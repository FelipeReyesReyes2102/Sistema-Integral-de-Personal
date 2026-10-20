import { useEffect, useState } from 'react'
import { AlarmClock, Ban, DoorOpen, Footprints, Laptop, RefreshCw, Search, Send } from 'lucide-react'
import { api } from '../api'
import Avatar from '../components/Avatar'
import BuscadorPaciente from '../components/BuscadorPaciente'
import { CATEGORIAS, ESTADOS, fmtFecha } from '../utils'

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
  const filtra = (l) => l.filter((p) => !buscar || `${p.nombre} ${p.numero_empleado} ${p.departamento || ''}`.toLowerCase().includes(buscar.toLowerCase()))
  const horas = filtra(datos?.por_horas || [])
  const dias = filtra(datos?.por_dias || [])

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
          <input value={buscar} onChange={(e) => setBuscar(e.target.value)} placeholder="Buscar persona o nómina" />
        </div>
        <button className="btn btn-sm" onClick={cargar}><RefreshCw size={14} /> Actualizar</button>
      </div>
      {error && <div className="alerta error">{error}</div>}
      {datos && horas.length === 0 && dias.length === 0 && (
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

function Retardos() {
  const [emp, setEmp] = useState(null)
  const [hora, setHora] = useState(ahoraHHMM())
  const [motivo, setMotivo] = useState('')
  const [gh, setGh] = useState(false)
  const [lista, setLista] = useState([])
  const [msg, setMsg] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const cargar = () => api('/caseta/retardos').then(setLista).catch(() => {})
  useEffect(() => { cargar() }, [])
  useEffect(() => { setHora(ahoraHHMM()); setGh(false) }, [emp?.id])

  const retraso = emp?.entrada_hoy ? minutos(emp.entrada_hoy, hora) : 0
  const destino = !emp ? '' : gh || !emp.jefe_nombre ? 'Gestión Humana (GH)' : emp.jefe_nombre

  async function registrar() {
    setMsg(null)
    setEnviando(true)
    try {
      const r = await api('/caseta/retardos', { method: 'POST', body: { usuario_id: emp.id, hora_llegada: hora, motivo: motivo.trim() || null, enviar_gh: gh } })
      setMsg({ ok: true, t: `Retardo de ${r.nombre} registrado (${retraso} min). Se envió a ${r.va_a_gh ? 'GH' : r.aprobador_nombre} para validarlo.` })
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
        <b style={{ fontSize: 16 }}>Registrar retardo</b>
        <p className="muted" style={{ marginTop: 4, fontSize: 13 }}>
          Busca a la persona que llegó tarde. Se crea un permiso de <b>llegada tarde</b> que valida su jefe inmediato; si no tiene jefe o
          el jefe no está en planta, lo valida GH.
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
                <Send size={15} /> {enviando ? 'Registrando…' : 'Registrar retardo'}
              </button>
            </div>
          </div>
        )}
        {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`} style={{ marginTop: 12 }}>{msg.t}</div>}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <b>Retardos registrados hoy</b>
        <div className="tabla-wrap" style={{ marginTop: 10 }}>
          <table className="tabla">
            <thead><tr><th>Empleado</th><th>Entrada</th><th>Llegó</th><th>Valida</th><th>Estado</th><th /></tr></thead>
            <tbody>
              {lista.length === 0 && <tr><td colSpan={6} className="muted" style={{ textAlign: 'center' }}>Sin retardos registrados hoy.</td></tr>}
              {lista.map((r) => (
                <tr key={r.id}>
                  <td>{r.nombre}<div className="muted" style={{ fontSize: 12 }}>No. {r.numero_empleado}{r.departamento ? ` · ${r.departamento}` : ''}</div></td>
                  <td>{r.hora_inicio}</td>
                  <td><b>{r.hora_fin}</b> <span className="muted">({minutos(r.hora_inicio, r.hora_fin)} min)</span></td>
                  <td className="muted">{r.estado === 'solicitado' ? (r.va_a_gh ? 'GH' : r.aprobador_nombre) : r.autorizo}</td>
                  <td>
                    <span className={`pill ${r.estado}`}>{ESTADOS[r.estado]}</span>
                    {r.motivo_rechazo && <div style={{ fontSize: 11, color: 'var(--danger)' }}>{r.motivo_rechazo}</div>}
                  </td>
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
