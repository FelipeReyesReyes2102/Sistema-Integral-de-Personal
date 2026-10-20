import { useEffect, useMemo, useState } from 'react'
import { CalendarRange, Eye, Search } from 'lucide-react'
import { api } from '../api'
import SedeActual from '../components/SedeActual'
import { hoyISO, num } from '../utils'

/** GH programa vacaciones a varios empleados a la vez (p. ej. planta); sin saldo, quedan con saldo negativo. */
export default function Planeacion() {
  const [usuarios, setUsuarios] = useState([])
  const [grupos, setGrupos] = useState([])
  const [filtro, setFiltro] = useState({ grupo: '', soloPlanta: true, q: '' })
  const [elegidos, setElegidos] = useState(new Set())
  const [form, setForm] = useState({ fecha_inicio: hoyISO(), fecha_fin: hoyISO(), comentario: '' })
  const [previa, setPrevia] = useState(null)
  const [aplicada, setAplicada] = useState(false)
  const [msg, setMsg] = useState(null)
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    api('/usuarios', { query: { activos: true } }).then(setUsuarios).catch((e) => setMsg({ ok: false, t: e.message }))
    api('/grupos').then(setGrupos).catch(() => {})
  }, [])

  const visibles = useMemo(() => usuarios.filter((u) =>
    (!filtro.soloPlanta || u.rol === 'planta')
    && (!filtro.grupo || String(u.grupo_id) === filtro.grupo)
    && (!filtro.q || u.nombre.toLowerCase().includes(filtro.q.toLowerCase()))), [usuarios, filtro])

  const cambiar = (cambio) => { setPrevia(null); setAplicada(false); cambio() }
  const toggle = (id) => cambiar(() => setElegidos((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n }))
  const todos = visibles.length > 0 && visibles.every((u) => elegidos.has(u.id))
  const toggleTodos = () => cambiar(() => setElegidos((s) => {
    const n = new Set(s)
    visibles.forEach((u) => (todos ? n.delete(u.id) : n.add(u.id)))
    return n
  }))
  const setF = (k) => (e) => cambiar(() => setForm({ ...form, [k]: e.target.value }))

  async function correr(ruta) {
    setOcupado(true)
    setMsg(null)
    try {
      const r = await api(ruta, { method: 'POST', body: { ...form, usuario_ids: [...elegidos] } })
      setPrevia(r)
      return r
    } catch (e) {
      setMsg({ ok: false, t: e.message })
      return null
    } finally {
      setOcupado(false)
    }
  }
  const verPrevia = () => correr('/vacaciones/planeacion/previa')
  async function aplicar() {
    const conDeuda = (previa || []).filter((f) => !f.error && f.negativo > 0).length
    const n = (previa || []).filter((f) => !f.error).length
    if (!window.confirm(`¿Programar las vacaciones a ${n} empleado(s)?${conDeuda ? ` ${conDeuda} quedarán con saldo negativo.` : ''} Quedan validadas.`)) return
    const r = await correr('/vacaciones/planeacion')
    if (r) {
      setAplicada(true)
      setMsg({ ok: true, t: `Vacaciones programadas a ${r.filter((f) => f.solicitudes.length).length} empleado(s).` })
      api('/usuarios', { query: { activos: true } }).then(setUsuarios).catch(() => {})
    }
  }

  return (
    <>
      <SedeActual que="La planeación" />
      <div className="card">
        <h3 className="fila" style={{ gap: 8, marginBottom: 6 }}><CalendarRange size={18} /> Planeación general de vacaciones</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
          Programa vacaciones a varios empleados a la vez (por ejemplo, un paro de planta). Se descuentan los días laborales de
          cada uno según su ciclo y quedan <b>validadas</b>. Si alguien no tiene saldo suficiente, queda con <b>saldo negativo</b> y
          se le descuenta de los próximos días que genere (aniversario, año calendario o mes, según la sede).
        </p>
        <div className="pl-grid">
          <label className="campo">Desde<input type="date" value={form.fecha_inicio} onChange={setF('fecha_inicio')} /></label>
          <label className="campo">Hasta<input type="date" value={form.fecha_fin} min={form.fecha_inicio} onChange={setF('fecha_fin')} /></label>
          <label className="campo pl-com">Motivo / comentario<input value={form.comentario} onChange={setF('comentario')} placeholder="Ej. Paro técnico de planta" maxLength={300} /></label>
        </div>
      </div>

      <div className="card">
        <div className="fila" style={{ gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
          <label className="checkbox"><input type="checkbox" checked={filtro.soloPlanta} onChange={(e) => setFiltro({ ...filtro, soloPlanta: e.target.checked })} /> Solo personal de planta</label>
          <select value={filtro.grupo} onChange={(e) => setFiltro({ ...filtro, grupo: e.target.value })}>
            <option value="">Todos los grupos</option>
            {grupos.map((g) => <option key={g.id} value={g.id}>{g.nombre}</option>)}
          </select>
          <span className="bt-input-icono" style={{ width: 240 }}><Search size={14} /><input value={filtro.q} onChange={(e) => setFiltro({ ...filtro, q: e.target.value })} placeholder="Buscar empleado…" /></span>
          <div className="espacio" />
          <span className="muted" style={{ fontSize: 13 }}>{elegidos.size} seleccionado(s)</span>
          <button className="btn btn-sm" disabled={!elegidos.size || ocupado} onClick={verPrevia}><Eye size={14} /> Vista previa</button>
        </div>
        <div className="tabla-wrap" style={{ maxHeight: 340, overflowY: 'auto' }}>
          <table className="tabla">
            <thead><tr><th style={{ width: 30 }}><input type="checkbox" checked={todos} onChange={toggleTodos} title="Seleccionar todos" /></th><th>Empleado</th><th>Grupo</th><th>Jornada</th><th>Saldo actual</th></tr></thead>
            <tbody>
              {visibles.length === 0 && <tr><td colSpan={5} className="muted" style={{ textAlign: 'center' }}>No hay empleados con esos filtros.</td></tr>}
              {visibles.map((u) => (
                <tr key={u.id} onClick={() => toggle(u.id)} style={{ cursor: 'pointer' }}>
                  <td><input type="checkbox" checked={elegidos.has(u.id)} onChange={() => toggle(u.id)} onClick={(e) => e.stopPropagation()} /></td>
                  <td>{u.nombre}<div className="muted" style={{ fontSize: 11 }}>{u.numero_empleado}</div></td>
                  <td>{u.grupo_nombre || '—'}</td>
                  <td>{u.tipo_jornada_nombre || (u.rol === 'planta' ? 'Planta' : 'Oficina')}</td>
                  <td className={u.saldo_dias < 0 ? 'texto-error' : ''}>{u.saldo_dias !== null && u.saldo_dias !== undefined ? `${num(u.saldo_dias)} d` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {previa && (
        <div className="card">
          <h4 style={{ margin: '0 0 8px' }}>{aplicada ? 'Resultado' : 'Vista previa'}</h4>
          <div className="tabla-wrap">
            <table className="tabla">
              <thead><tr><th>Empleado</th><th>Grupo</th><th>Días</th><th>Saldo antes</th><th>Saldo después</th><th>Observaciones</th></tr></thead>
              <tbody>
                {previa.map((f) => (
                  <tr key={f.usuario_id} style={{ opacity: f.error ? 0.6 : 1 }}>
                    <td>{f.nombre}</td>
                    <td>{f.grupo || '—'}</td>
                    <td>{f.dias} d <span className="muted">({num(f.horas)} h)</span></td>
                    <td>{num(f.saldo_antes)} d</td>
                    <td className={f.saldo_despues < 0 ? 'texto-error' : ''}><b>{num(f.saldo_despues)} d</b></td>
                    <td>{f.error
                      ? <span className="texto-error">{f.error} No se programa.</span>
                      : f.negativo > 0 ? <span className="pl-deuda">{num(f.negativo)} d a descontar de sus próximos días</span>
                        : aplicada && f.solicitudes.length ? 'Programadas' : 'Con saldo suficiente'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!aplicada && (
            <div className="fila" style={{ marginTop: 10 }}>
              <div className="espacio" />
              <button className="btn btn-primary" disabled={ocupado || !previa.some((f) => !f.error)} onClick={aplicar}>
                <CalendarRange size={15} /> Programar vacaciones
              </button>
            </div>
          )}
        </div>
      )}
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
    </>
  )
}
