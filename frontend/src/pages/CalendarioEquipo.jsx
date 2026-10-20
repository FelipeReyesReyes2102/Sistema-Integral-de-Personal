import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { api } from '../api'
import Avatar from '../components/Avatar'
import EventosDia from '../components/EventosDia'
import { CATEGORIAS, DIAS_SEMANA, ESTADOS, MESES, ROLES, estiloEvento, hoyISO } from '../utils'

const CATS = ['vacaciones', 'home_office', 'llegada_tarde', 'salida_temprana', 'salida_intermedia', 'otro_permiso', 'consulta', 'incapacidad']

/** Calendario general (administrador): vacaciones, permisos, home office y consultas de todo el personal. */
export default function CalendarioEquipo() {
  const hoy = new Date()
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [filtros, setFiltros] = useState({ grupo_id: '', rol: '', q: '' })
  const [foco, setFoco] = useState(null)
  const [soloConEventos, setSoloConEventos] = useState(false)
  const [grupos, setGrupos] = useState([])
  const [datos, setDatos] = useState(null)
  const [detalle, setDetalle] = useState(null)
  const hoyIso = hoyISO()

  useEffect(() => { api('/grupos').then(setGrupos) }, [])
  useEffect(() => {
    const t = setTimeout(() => {
      api('/calendario/equipo', { query: { anio, mes, ...filtros } }).then(setDatos).catch((e) => alert(e.message))
    }, 200)
    return () => clearTimeout(t)
  }, [anio, mes, filtros])

  function mover(delta) {
    let m = mes + delta, a = anio
    if (m < 1) { m = 12; a -= 1 }
    if (m > 12) { m = 1; a += 1 }
    setMes(m)
    setAnio(a)
  }

  const dias = Array.from({ length: datos?.total_dias || 0 }, (_, i) => i + 1)
  const iso = (d) => `${anio}-${String(mes).padStart(2, '0')}-${String(d).padStart(2, '0')}`
  const visibles = (evs) => evs.filter((e) => !foco || e.cat === foco)

  // Conteo por categoría (eventos por día) para la leyenda
  const conteo = useMemo(() => {
    const c = Object.fromEntries(CATS.map((k) => [k, 0]))
    for (const e of datos?.empleados || []) for (const d of Object.values(e.dias)) for (const ev of d.eventos) if (c[ev.cat] !== undefined) c[ev.cat] += 1
    return c
  }, [datos])

  const empleados = (datos?.empleados || []).filter((e) => !soloConEventos
    || Object.values(e.dias).some((d) => visibles(d.eventos).length))

  const f = (k) => (e) => setFiltros({ ...filtros, [k]: e.target.value })

  return (
    <div className="card">
      <div className="fila" style={{ marginBottom: 12 }}>
        <div className="cal-nav">
          <button onClick={() => mover(-1)} aria-label="Mes anterior"><ChevronLeft size={16} /></button>
          <button className="zoom-titulo">{MESES[mes - 1]} {anio}</button>
          <button onClick={() => mover(1)} aria-label="Mes siguiente"><ChevronRight size={16} /></button>
        </div>
        <button className="btn btn-sm" onClick={() => { setAnio(hoy.getFullYear()); setMes(hoy.getMonth() + 1) }}>Hoy</button>
        <input style={{ width: 200 }} placeholder="Buscar empleado…" value={filtros.q} onChange={f('q')} />
        <select style={{ width: 160 }} value={filtros.rol} onChange={f('rol')}>
          <option value="">Todos los tipos</option>
          {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select style={{ width: 150 }} value={filtros.grupo_id} onChange={f('grupo_id')}>
          <option value="">Todos los grupos</option>
          {grupos.map((g) => <option key={g.id} value={g.id}>{g.nombre}</option>)}
        </select>
        <label className="checkbox"><input type="checkbox" checked={soloConEventos} onChange={(e) => setSoloConEventos(e.target.checked)} /> Solo con eventos</label>
      </div>

      <div className="cal-leyenda" style={{ marginTop: 0, marginBottom: 12, justifyContent: 'flex-start' }}>
        {CATS.map((k) => (
          <button key={k} type="button" className={`ley-chip ${foco === k ? 'activo' : ''} ${foco && foco !== k ? 'apagado' : ''}`}
            onClick={() => setFoco(foco === k ? null : k)}>
            <i style={{ background: CATEGORIAS[k].color }} /> {CATEGORIAS[k].label} <b>{conteo[k]}</b>
          </button>
        ))}
        <span className="ley-chip estatico"><i style={{ background: '#fde3e1' }} /> Festivo</span>
        <span className="ley-chip estatico"><i style={{ background: '#eef0f3' }} /> Descanso</span>
        <span className="ley-estados">
          <i style={estiloEvento('vacaciones', 'validado')}>A</i> Aprobado
          <i style={estiloEvento('vacaciones', 'solicitado')}>P</i> Pendiente
          <i style={estiloEvento('vacaciones', 'borrador')}>B</i> Borrador
        </span>
      </div>

      <div className="equipo-wrap">
        <table className="equipo">
          <thead>
            <tr>
              <th className="nombre">Empleado</th>
              {dias.map((d) => {
                const fecha = iso(d)
                const dow = (new Date(anio, mes - 1, d).getDay() + 6) % 7
                return (
                  <th key={d} className={`${dow >= 5 ? 'finde' : ''} ${fecha === hoyIso ? 'hoy' : ''}`}>
                    <div className="eq-dow">{DIAS_SEMANA[dow]}</div>{d}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {empleados.length === 0 && (
              <tr><td className="nombre muted" colSpan={dias.length + 1} style={{ padding: 20 }}>Sin empleados para estos filtros.</td></tr>
            )}
            {empleados.map((e) => (
              <tr key={e.id}>
                <td className="nombre">
                  <div className="persona">
                    <Avatar usuario={e} tam={28} />
                    <div>
                      <div style={{ fontWeight: 500 }}>{e.nombre}</div>
                      <div className="muted" style={{ fontSize: 10 }}>
                        {ROLES[e.rol]}{e.grupo && <> · <span style={{ color: e.grupo_color }}>{e.grupo}</span></>}{e.turno && ` · ${e.turno}`}
                      </div>
                    </div>
                  </div>
                </td>
                {dias.map((d) => {
                  const fecha = iso(d)
                  const info = e.dias[fecha] || { eventos: [] }
                  const evs = visibles(info.eventos)
                  const clases = ['eq-celda']
                  if (info.base) clases.push(info.base)
                  if (fecha === hoyIso) clases.push('hoy')
                  if (evs.length) clases.push('con-eventos')
                  const titulo = [info.festivo && `Festivo: ${info.festivo}`, info.base === 'descanso' && 'Descanso',
                    ...evs.map((x) => `${CATEGORIAS[x.cat]?.label}${x.estado !== 'registrada' ? ` · ${ESTADOS[x.estado]}` : ''}`)]
                    .filter(Boolean).join('\n')
                  return (
                    <td key={d} className={clases.join(' ')} title={titulo}
                      onClick={() => evs.length && setDetalle({ empleado: e, fecha, info })}>
                      <div className="eq-eventos">
                        {evs.slice(0, 3).map((x, i) => <span key={i} className="eq-ev" style={estiloEvento(x.cat, x.estado)} />)}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>Clic en una celda con eventos para ver sus detalles.</div>

      {detalle && (
        <EventosDia fecha={detalle.fecha} eventos={detalle.info.eventos} persona={detalle.empleado.nombre}
          festivo={detalle.info.festivo} descanso={detalle.info.base === 'descanso'} onClose={() => setDetalle(null)} />
      )}
    </div>
  )
}
