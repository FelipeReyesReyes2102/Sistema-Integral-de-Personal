import { useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, LayoutGrid } from 'lucide-react'
import { CATEGORIAS, DIAS_SEMANA, ESTADOS, MESES, eventosPorFecha, estiloEvento, fmtFecha, hoyISO, parseISO, toISO } from '../utils'

const PRIORIDAD = ['vacaciones', 'home_office', 'salida_intermedia', 'salida_temprana', 'llegada_tarde', 'consulta', 'consulta_medica']

/**
 * Calendario interactivo.
 * - Clic en un día con eventos: abre sus detalles (`onDia`).
 * - Clic en un día libre: selecciona el rango para una nueva solicitud (`onSeleccion`).
 * - `foco`: muestra solo una categoría (se elige en la leyenda o en el panel de registros).
 * - Los días anteriores a hoy no se pueden seleccionar: solo se consultan (historial).
 * - `franjas`: [{desde, hasta, color, nombre}] fondo claro de cada periodo vacacional, para ver dónde cambia.
 * - `maxDias`: días laborales disponibles; al elegir el segundo día no se puede pasar de ese límite.
 */
export default function YearCalendar({ anio, onAnio, datos, seleccion, onSeleccion, onDia, foco, onFoco, franjas = [],
  maxDias = null, compacto = false }) {
  const [vista, setVista] = useState('anio')
  const [mes, setMes] = useState(new Date().getMonth())
  const [hover, setHover] = useState(null)
  const seleccionable = typeof onSeleccion === 'function'
  const hoy = hoyISO()

  const festivos = Object.fromEntries((datos?.festivos || []).map((f) => [f.fecha, f.nombre]))
  const cumples = {}
  for (const c of datos?.cumpleanos || []) (cumples[c.fecha] ||= []).push(c)
  const noLab = new Set(datos?.no_laborables || [])
  const todos = eventosPorFecha(datos)
  const eventosDe = (f) => (todos[f] || []).filter((e) => !foco || foco === e.cat || (foco === 'consulta' && e.cat === 'consulta_medica'))
  const anios = Array.from({ length: 7 }, (_, i) => new Date().getFullYear() - 4 + i)

  const pasado = (f) => f < hoy

  // Límite de la selección: desde el primer día elegido, hasta donde alcanzan los días disponibles
  const esLaboral = (f) => {
    if (f.slice(0, 4) === String(anio)) return !noLab.has(f) && !festivos[f]
    const dow = parseISO(f).getDay() // fuera del año cargado se aproxima con lunes a viernes
    return dow !== 0 && dow !== 6
  }
  let limites = null
  if (seleccionable && seleccion?.inicio && !seleccion.fin && maxDias !== null) {
    const maximo = Math.max(0, Math.floor(maxDias + 1e-6))
    const caminar = (paso) => {
      const d = parseISO(seleccion.inicio)
      let ultimo = seleccion.inicio
      let n = 0
      for (let i = 0; i < 500; i++) {
        const f = toISO(d)
        if (pasado(f)) break
        if (esLaboral(f) && ++n > maximo) break
        ultimo = f
        d.setDate(d.getDate() + paso)
      }
      return ultimo
    }
    limites = [caminar(-1), caminar(1)]
  }
  const fuera = (f) => !!limites && (f < limites[0] || f > limites[1])
  const franjaDe = (f) => franjas.find((x) => f >= x.desde && f <= x.hasta)
  const franjasDelAnio = franjas.filter((x) => x.desde <= `${anio}-12-31` && x.hasta >= `${anio}-01-01`)
  const hoverValido = hover && !pasado(hover) && !fuera(hover) ? hover : null
  let [ri, rf] = [seleccion?.inicio, seleccion?.fin || (seleccion?.inicio && hoverValido) || seleccion?.inicio]
  if (ri && rf && rf < ri) [ri, rf] = [rf, ri]
  const enRango = (f) => ri && f >= ri && f <= rf

  function seleccionar(fecha) {
    if (!seleccionable || pasado(fecha) || fuera(fecha)) return
    if (!seleccion?.inicio || seleccion.fin) return onSeleccion({ inicio: fecha, fin: null })
    if (fecha === seleccion.inicio) return onSeleccion({ inicio: fecha, fin: fecha })
    const [a, b] = fecha < seleccion.inicio ? [fecha, seleccion.inicio] : [seleccion.inicio, fecha]
    onSeleccion({ inicio: a, fin: b })
  }

  function clicDia(fecha) {
    const evs = eventosDe(fecha)
    if ((evs.length || (festivos[fecha] && foco === 'festivo')) && onDia && !(seleccion?.inicio && !seleccion.fin)) {
      onDia(fecha)
    } else {
      seleccionar(fecha)
    }
  }

  function diasDelMes(m) {
    const offset = (new Date(anio, m, 1).getDay() + 6) % 7
    const total = new Date(anio, m + 1, 0).getDate()
    return { offset, fechas: Array.from({ length: total }, (_, i) => toISO(new Date(anio, m, i + 1))) }
  }

  function irMes(delta) {
    let m = mes + delta
    if (m < 0) { m = 11; onAnio(anio - 1) }
    if (m > 11) { m = 0; onAnio(anio + 1) }
    setMes(m)
  }

  function irHoy() {
    const d = new Date()
    onAnio(d.getFullYear())
    setMes(d.getMonth())
  }

  const principal = (evs) => [...evs].sort((a, b) => PRIORIDAD.indexOf(a.cat) - PRIORIDAD.indexOf(b.cat))[0]
  const titulo = (f, evs) => [
    cumples[f] && `🎂 Cumpleaños: ${cumples[f].map((c) => c.nombre).join(', ')}`,
    festivos[f] && `Festivo: ${festivos[f]}`,
    noLab.has(f) && 'Día de descanso',
    ...evs.map((e) => `${CATEGORIAS[e.cat]?.label}${e.estado && e.estado !== 'registrada' ? ` · ${ESTADOS[e.estado]}` : ''}${e.hora_inicio && e.cat !== 'home_office' ? ` · ${e.hora_inicio}` : ''}`),
  ].filter(Boolean).join('\n')

  // ---------- Celda pequeña (vista anual) ----------
  function dia(f) {
    const evs = eventosDe(f)
    const p = principal(evs)
    const clases = ['cd']
    if (noLab.has(f)) clases.push('cd-descanso')
    if (festivos[f]) clases.push('cd-festivo')
    if (f === hoy) clases.push('cd-hoy')
    if (cumples[f]) clases.push('cd-cumple')
    if (enRango(f)) clases.push(noLab.has(f) || festivos[f] ? 'cd-rango-excluido' : 'cd-rango')
    if (f === ri || f === rf) clases.push('cd-rango-ext')
    if (evs.length || (seleccionable && !pasado(f))) clases.push('cd-clic')
    if (seleccionable && pasado(f) && !evs.length) clases.push('cd-pasado')
    if (fuera(f) && !pasado(f)) clases.push('cd-fuera')
    if (foco && !evs.length && !(foco === 'festivo' && festivos[f])) clases.push('cd-atenuado')
    const fr = franjaDe(f)
    if (fr) clases.push('cd-franja')
    if (fr && fr.desde === f) clases.push('cd-franja-inicio')
    const estilo = p && !enRango(f) ? estiloEvento(p.cat, p.estado) : fr ? { '--franja': fr.color } : undefined
    return (
      <button key={f} type="button" className={clases.join(' ')} style={estilo}
        title={[fr && (fr.desde === f ? `Inicia el ${fr.nombre}` : fr.nombre), titulo(f, evs)].filter(Boolean).join('\n')}
        onClick={() => clicDia(f)} onMouseEnter={() => setHover(f)}>
        {Number(f.slice(8))}
        {evs.length > 1 && (
          <span className="cd-puntos">
            {evs.slice(1, 4).map((e, i) => <i key={i} style={{ background: CATEGORIAS[e.cat]?.color }} />)}
          </span>
        )}
      </button>
    )
  }

  const nav = (
    <div className="cal-barra">
      <div className="cal-vistas">
        <button className={vista === 'anio' ? 'activo' : ''} onClick={() => setVista('anio')}><LayoutGrid size={14} /> Año</button>
        <button className={vista === 'mes' ? 'activo' : ''} onClick={() => setVista('mes')}><CalendarDays size={14} /> Mes</button>
      </div>
      <button className="btn btn-sm" onClick={irHoy}>Hoy</button>
      <div className="espacio" />
      {vista === 'anio' ? (
        <div className="cal-nav">
          <button onClick={() => onAnio(anio - 1)} aria-label="Año anterior"><ChevronLeft size={16} /></button>
          <select value={anio} onChange={(e) => onAnio(Number(e.target.value))}>
            {anios.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <button onClick={() => onAnio(anio + 1)} aria-label="Año siguiente"><ChevronRight size={16} /></button>
        </div>
      ) : (
        <div className="cal-nav">
          <button onClick={() => irMes(-1)} aria-label="Mes anterior"><ChevronLeft size={16} /></button>
          <button className="zoom-titulo">{MESES[mes]} {anio}</button>
          <button onClick={() => irMes(1)} aria-label="Mes siguiente"><ChevronRight size={16} /></button>
        </div>
      )}
    </div>
  )

  return (
    <div className="yc" onMouseLeave={() => setHover(null)}>
      {nav}
      {seleccionable && !compacto && (
        <div className="cal-tip">
          Clic en un evento para ver sus detalles · clic en días libres (de hoy en adelante) para seleccionar un rango · clic en el nombre del mes para ampliarlo
        </div>
      )}

      {vista === 'anio' ? (
        <div className="cal-grid">
          {MESES.map((nombre, m) => {
            const { offset, fechas } = diasDelMes(m)
            return (
              <div className="mes" key={nombre}>
                <h4><button className="mes-titulo" onClick={() => { setMes(m); setVista('mes') }} title="Ampliar mes">{nombre}</button></h4>
                <div className="mes-grid">
                  {DIAS_SEMANA.map((d) => <div key={d} className="cab">{d}</div>)}
                  {Array.from({ length: offset }, (_, i) => <div key={`v${i}`} />)}
                  {fechas.map((f) => dia(f))}
                </div>
              </div>
            )
          })}
        </div>
      ) : (() => {
        const { offset, fechas } = diasDelMes(mes)
        return (
          <div className="zoom-grid">
            {DIAS_SEMANA.map((d) => <div key={d} className="zoom-cab">{d}</div>)}
            {Array.from({ length: offset }, (_, i) => <div key={`v${i}`} className="zoom-vacio" />)}
            {fechas.map((f) => {
              const evs = eventosDe(f)
              const clases = ['zoom-dia']
              if (seleccionable && !pasado(f)) clases.push('clic')
              if (seleccionable && pasado(f)) clases.push('pasado')
              if (fuera(f) && !pasado(f)) clases.push('fuera')
              if (noLab.has(f)) clases.push('nolab')
              if (f === hoy) clases.push('hoy')
              if (enRango(f)) clases.push(noLab.has(f) || festivos[f] ? 'rango-excluido' : 'rango')
              if (f === ri || f === rf) clases.push('rango-ext')
              const fr = franjaDe(f)
              if (fr) clases.push('franja')
              return (
                <div key={f} className={clases.join(' ')} onClick={() => seleccionar(f)} onMouseEnter={() => setHover(f)}
                  style={fr ? { '--franja': fr.color } : undefined} title={fr?.nombre}>
                  <span className="zoom-num">{Number(f.slice(8))}</span>
                  {fr && fr.desde === f && <span className="zoom-chip franja-chip">Inicia {fr.nombre}</span>}
                  {festivos[f] && <span className="zoom-chip rojo">{festivos[f]}</span>}
                  {(cumples[f] || []).map((c) => <span key={c.usuario_id} className="zoom-chip cumple" title="Cumpleaños">🎂 {c.nombre}</span>)}
                  {noLab.has(f) && !evs.length && <span className="zoom-chip gris">Descanso</span>}
                  {evs.map((e, i) => (
                    <button key={i} type="button" className="zoom-chip evento" style={estiloEvento(e.cat, e.estado)}
                      title="Ver detalles" onClick={(ev) => { ev.stopPropagation(); onDia?.(f) }}>
                      {CATEGORIAS[e.cat]?.label}
                      {e.hora_inicio && !['vacaciones', 'home_office'].includes(e.cat) ? ` · ${e.hora_inicio}` : ''}
                      {e.estado === 'solicitado' ? ' (pendiente)' : e.estado === 'borrador' ? ' (borrador)' : ''}
                    </button>
                  ))}
                </div>
              )
            })}
          </div>
        )
      })()}

      {!compacto && <div className="cal-leyenda">
        {Object.entries(CATEGORIAS).filter(([k]) => k !== 'consulta_medica').map(([k, c]) => (
          <button key={k} type="button" className={`ley-chip ${foco === k ? 'activo' : ''} ${foco && foco !== k ? 'apagado' : ''}`}
            onClick={() => onFoco?.(foco === k ? null : k)} disabled={!onFoco}>
            <i style={{ background: c.color }} /> {c.label}
          </button>
        ))}
        {franjasDelAnio.map((x) => (
          <span key={x.desde} className="ley-chip estatico ley-franja" style={{ '--franja': x.color }}
            title={`Del ${fmtFecha(x.desde, false)}${x.hasta < '9999' ? ` al ${fmtFecha(x.hasta, false)}` : ' en adelante'}`}>
            <i /> {x.nombre}
          </span>
        ))}
        <span className="ley-estados">
          <i style={estiloEvento('vacaciones', 'validado')}>A</i> Aprobado
          <i style={estiloEvento('vacaciones', 'solicitado')}>P</i> Pendiente
          <i style={estiloEvento('vacaciones', 'borrador')}>B</i> Borrador
        </span>
      </div>}
    </div>
  )
}
