import { useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, LayoutGrid } from 'lucide-react'
import IconoCategoria from './IconoCategoria'
import { CATEGORIAS, DIAS_SEMANA, ESTADOS, MESES, eventosPorFecha, estiloEvento, fmtFecha, hoyISO, parseISO, toISO } from '../utils'

const PRIORIDAD = ['incapacidad', 'vacaciones', 'home_office', 'otro_permiso', 'salida_intermedia', 'salida_temprana', 'llegada_tarde', 'consulta', 'consulta_medica']

/**
 * Calendario interactivo.
 * - Clic izquierdo: selecciona el rango para una nueva solicitud (`onSeleccion`). Si el día no se puede
 *   seleccionar (pasado, fuera del saldo o solo consulta) y tiene eventos, abre sus detalles.
 * - Clic derecho: abre la ventana del día con sus eventos y cumpleaños (`onDia`).
 * - `foco`: muestra solo una categoría (se elige en la leyenda o en el panel de registros).
 * - Los días anteriores a hoy no se pueden seleccionar: solo se consultan (historial).
 * - `franjas`: [{desde, hasta, color, nombre}] fondo claro de cada periodo vacacional, para ver dónde cambia.
 * - `maxDias`: días laborales disponibles; al elegir el segundo día no se puede pasar de ese límite.
 * - `fechaMax`: último día que se puede seleccionar (vencimiento del periodo: aniversario + 18 meses).
 * - `foco`: categoría resaltada (sus días palpitan y el resto se atenúa).
 * - `aniversario`: {fecha, titulo} aniversario de ingreso del empleado en el año (siempre resaltado).
 */
export default function YearCalendar({ anio, onAnio, datos, seleccion, onSeleccion, onDia, foco, onFoco, franjas = [],
  maxDias = null, fechaMax = null, compacto = false, aniversario = null }) {
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
        if (pasado(f) || (fechaMax && f > fechaMax)) break
        if (esLaboral(f) && ++n > maximo) break
        ultimo = f
        d.setDate(d.getDate() + paso)
      }
      return ultimo
    }
    limites = [caminar(-1), caminar(1)]
  }
  // Fuera de lo seleccionable: después del vencimiento del periodo o, al elegir el último día, más allá del saldo
  const fuera = (f) => (seleccionable && !!fechaMax && f > fechaMax) || (!!limites && (f < limites[0] || f > limites[1]))
  const resaltado = (f, evs) => !!foco && (evs.length > 0 || (foco === 'festivo' && !!festivos[f]) || (foco === 'cumpleanos' && !!cumples[f]))
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

  const conInfo = (f) => eventosDe(f).length > 0 || !!festivos[f] || !!cumples[f] || aniversario?.fecha === f

  function clicDia(fecha) {
    if (seleccionable && !pasado(fecha) && !fuera(fecha)) return seleccionar(fecha)
    if (onDia && conInfo(fecha)) onDia(fecha)
  }

  function verDia(e, fecha) {
    if (!onDia) return
    e.preventDefault() // reemplaza el menú contextual del navegador
    onDia(fecha)
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
  const miCumple = (f) => (cumples[f] || []).some((c) => c.propio)
  const esAniversario = (f) => aniversario?.fecha === f
  const titulo = (f, evs) => [
    esAniversario(f) && `🏅 ${aniversario.titulo}`,
    miCumple(f) && '🎂 ¡Tu cumpleaños!',
    cumples[f] && `🎂 Cumpleaños: ${cumples[f].map((c) => c.nombre).join(', ')}`,
    festivos[f] && `Festivo: ${festivos[f]}`,
    noLab.has(f) && 'Día de descanso',
    ...evs.map((e) => `${e.tipo_nombre && e.cat === 'otro_permiso' ? e.tipo_nombre : CATEGORIAS[e.cat]?.label}${e.estado && e.estado !== 'registrada' ? ` · ${ESTADOS[e.estado]}` : ''}${e.hora_inicio && e.cat !== 'home_office' ? ` · ${e.hora_inicio}` : ''}`),
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
    if (miCumple(f)) clases.push('cd-mi-cumple')
    if (esAniversario(f)) clases.push('cd-aniversario')
    if (enRango(f)) clases.push(noLab.has(f) || festivos[f] ? 'cd-rango-excluido' : 'cd-rango')
    if (f === ri || f === rf) clases.push('cd-rango-ext')
    if (conInfo(f) || (seleccionable && !pasado(f))) clases.push('cd-clic')
    if (seleccionable && pasado(f) && !evs.length) clases.push('cd-pasado')
    if (fuera(f) && !pasado(f)) clases.push('cd-fuera')
    if (resaltado(f, evs)) clases.push('cd-foco')
    else if (foco) clases.push('cd-atenuado')
    const fr = franjaDe(f)
    if (fr) clases.push('cd-franja')
    if (fr && fr.desde === f) clases.push('cd-franja-inicio')
    const estilo = p && !enRango(f) ? estiloEvento(p.cat, p.estado) : fr ? { '--franja': fr.color } : undefined
    return (
      <button key={f} type="button" className={clases.join(' ')} style={estilo}
        title={[fr && (fr.desde === f ? `Inicia el ${fr.nombre}` : fr.nombre), titulo(f, evs)].filter(Boolean).join('\n')}
        onClick={() => clicDia(f)} onContextMenu={(e) => verDia(e, f)} onMouseEnter={() => setHover(f)}>
        {Number(f.slice(8))}
        {(esAniversario(f) || miCumple(f)) && (
          <span className={`cd-insignia ${esAniversario(f) ? 'aniv' : 'cumple'}`}>
            <IconoCategoria cat={esAniversario(f) ? 'aniversario' : 'cumpleanos'} size={9} strokeWidth={2.6} />
          </span>
        )}
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
          Clic izquierdo: seleccionar días para una solicitud · clic derecho: ver eventos y cumpleaños del día · clic en el nombre del mes para ampliarlo
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
              if (resaltado(f, evs)) clases.push('foco')
              else if (foco) clases.push('atenuado')
              if (noLab.has(f)) clases.push('nolab')
              if (f === hoy) clases.push('hoy')
              if (enRango(f)) clases.push(noLab.has(f) || festivos[f] ? 'rango-excluido' : 'rango')
              if (f === ri || f === rf) clases.push('rango-ext')
              const fr = franjaDe(f)
              if (fr) clases.push('franja')
              return (
                <div key={f} className={clases.join(' ')} onClick={() => clicDia(f)} onContextMenu={(e) => verDia(e, f)}
                  onMouseEnter={() => setHover(f)}
                  style={fr ? { '--franja': fr.color } : undefined} title={fr?.nombre}>
                  <span className="zoom-num">{Number(f.slice(8))}</span>
                  {fr && fr.desde === f && <span className="zoom-chip franja-chip">Inicia {fr.nombre}</span>}
                  {esAniversario(f) && <span className="zoom-chip aniv"><IconoCategoria cat="aniversario" size={11} /> {aniversario.titulo}</span>}
                  {festivos[f] && <span className="zoom-chip rojo"><IconoCategoria cat="festivo" size={11} /> {festivos[f]}</span>}
                  {(cumples[f] || []).map((c) => (
                    <span key={c.usuario_id} className="zoom-chip cumple" title="Cumpleaños">
                      <IconoCategoria cat="cumpleanos" size={11} /> {c.propio ? '¡Tu cumpleaños!' : c.nombre}
                    </span>
                  ))}
                  {noLab.has(f) && !evs.length && <span className="zoom-chip gris">Descanso</span>}
                  {evs.map((e, i) => (
                    <button key={i} type="button" className="zoom-chip evento" style={estiloEvento(e.cat, e.estado)}
                      title="Ver detalles" onClick={(ev) => { ev.stopPropagation(); onDia?.(f) }}>
                      <IconoCategoria cat={e.cat} size={11} /> {CATEGORIAS[e.cat]?.label}
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
