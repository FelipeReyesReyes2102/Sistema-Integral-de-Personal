import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Ban, Clock, Eye, EyeOff, FileText, Laptop, MousePointerClick, Pencil, Send, Stethoscope, Trash2, TreePalm, X,
} from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import Modal from '../components/Modal'
import PermisoModal from '../components/PermisoModal'
import VacacionesModal from '../components/VacacionesModal'
import YearCalendar from '../components/YearCalendar'
import PasosCadena from '../components/PasosCadena'
import {
  CATEGORIAS, esAdmin as esAdminFn, ESTADOS, ROLES, TIPOS_NOMINA, TIPOS_PERMISO_SOLICITABLES, ESTADOS_INCAPACIDAD, diaMes, nombreTipo, eventosPorFecha, estiloEvento, fmtFecha, hhmm, hoyISO, num,
  parseISO, toISO,
} from '../utils'
import EventosDia from '../components/EventosDia'
import MiTurno from '../components/MiTurno'
import Avatar from '../components/Avatar'
import IconoCategoria from '../components/IconoCategoria'
import DetalleConsulta from '../components/DetalleConsulta'
import SalidaEquipoModal from '../components/SalidaEquipoModal'
import FormatoEquipo from '../components/FormatoEquipo'
import { claseSituacion } from '../components/TablaSalidas'

// Color de cada periodo vacacional: el calendario pinta sus días con un tono claro de este color
const COLORES_PERIODO = ['#f9a825', '#7e57c2', '#00897b', '#d81b60', '#0288d1', '#ef6c00']
export const colorPeriodo = (p) => (p ? COLORES_PERIODO[(p.numero - 1) % COLORES_PERIODO.length] : COLORES_PERIODO[0])

const unAnioDespues = (iso) => toISO(new Date(Number(iso.slice(0, 4)) + 1, Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10))))
const diaAnterior = (iso) => { const d = parseISO(iso); d.setDate(d.getDate() - 1); return toISO(d) }

// Periodos cuyo color está oculto en el calendario (preferencia de este navegador)
const leerOcultos = () => {
  try { return JSON.parse(localStorage.getItem('sip-periodos-ocultos') || '[]') } catch { return [] }
}

export default function MisVacaciones({ usuarioId }) {
  const { user, recargar } = useAuth()
  const [empleado, setEmpleado] = useState(usuarioId ? null : user)
  const [periodos, setPeriodos] = useState([])
  const [periodoSel, setPeriodoSel] = useState(null)
  const [vacaciones, setVacaciones] = useState([])
  const [permisos, setPermisos] = useState([])
  const [consultas, setConsultas] = useState([])
  const [equipos, setEquipos] = useState([]) // mis salidas de equipo de cómputo (solo en mi propio calendario)
  const [anio, setAnio] = useState(new Date().getFullYear())
  const [calendario, setCalendario] = useState(null)
  const [tab, setTab] = useState('resumen')
  const [modal, setModal] = useState(null) // {tipo: 'vac'|'perm'|'ver'|'dia'|'consulta', item, tipoPermiso, inicial}
  const [lista, setLista] = useState(null) // categoría de Registros cuya lista de solicitudes está abierta ('todas' = todas)
  const [foco, setFoco] = useState(null) // categoría de Registros resaltada en el calendario
  const [ocultos, setOcultos] = useState(leerOcultos) // nombres de periodos sin color en el calendario
  useEffect(() => {
    try { localStorage.setItem('sip-periodos-ocultos', JSON.stringify(ocultos)) } catch { /* sin almacenamiento */ }
  }, [ocultos])
  const alternarPeriodo = (nombre) => setOcultos((o) => (o.includes(nombre) ? o.filter((x) => x !== nombre) : [...o, nombre]))
  const [seleccion, setSeleccion] = useState(null) // {inicio, fin} elegido en el calendario
  const [selCalc, setSelCalc] = useState(null)
  const [periodoSolicitud, setPeriodoSolicitud] = useState(null) // periodo del que se toman los días seleccionados
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const esAdmin = esAdminFn(user)
  const soloLectura = !!usuarioId && !esAdmin // jefe consultando a su personal
  const q = usuarioId ? { usuario_id: usuarioId } : undefined

  useEffect(() => {
    if (usuarioId) api(`/usuarios/${usuarioId}`).then(setEmpleado).catch((e) => setError(e.message))
  }, [usuarioId])
  // Política de la sede del empleado: permisos y módulos habilitados
  const [politica, setPolitica] = useState(null)
  useEffect(() => {
    api('/politica', { query: { usuario_id: usuarioId || user.id } }).then(setPolitica).catch(() => setPolitica(null))
  }, [usuarioId])
  const tiposPermiso = politica?.tipos_permiso || null
  const permisoHabilitado = (t) => !tiposPermiso || tiposPermiso.includes(t)
  const tiposSede = politica?.permisos_tipos || null
  const hayOtros = (tiposSede || []).some((t) => !t.base)

  const cargar = useCallback(async () => {
    try {
      const [ps, vs, pm, cs, eq] = await Promise.all([
        api('/periodos', { query: q }), api('/vacaciones', { query: q }), api('/permisos', { query: q }),
        api('/consultas', { query: q }).catch(() => []),
        usuarioId ? [] : api('/equipos').catch(() => []),
      ])
      setPeriodos(ps)
      setVacaciones(vs)
      setPermisos(pm)
      setConsultas(cs)
      setEquipos(eq)
      setPeriodoSel((sel) => (sel === 'general' || (sel && ps.some((p) => p.id === sel)) ? sel : (ps.find((p) => p.vigente) || ps[0])?.id ?? null))
    } catch (e) {
      setError(e.message)
    }
  }, [usuarioId])

  const cargarCalendario = useCallback(() => {
    api('/calendario', { query: { anio, ...q } }).then(setCalendario).catch((e) => setError(e.message))
  }, [anio, usuarioId])

  useEffect(() => { cargar() }, [cargar])
  useEffect(() => { cargarCalendario() }, [cargarCalendario])

  // Periodos de los que todavía se pueden tomar días (el más antiguo primero, para no perderlos)
  const periodosConSaldo = useMemo(() => periodos.filter((p) => p.vigente && p.horas_disponible > 0).reverse(), [periodos])
  // Modo General (por defecto con saldo en varios periodos): suma los periodos y descuenta primero el más antiguo
  const hayGeneral = periodosConSaldo.length > 1
  useEffect(() => {
    setPeriodoSolicitud((id) => (
      (id === 'general' && hayGeneral) || periodosConSaldo.some((p) => p.id === id) ? id
        : hayGeneral ? 'general' : periodosConSaldo[0]?.id ?? null))
  }, [periodosConSaldo])
  const esGeneral = periodoSolicitud === 'general'
  const periodoElegido = periodos.find((p) => p.id === periodoSolicitud)
  const diasGeneral = periodosConSaldo.reduce((t, p) => t + p.dias_disponible, 0)
  // No se pueden pedir días después del vencimiento del periodo (aniversario + 18 meses); en General, el más lejano
  const fechaMax = esGeneral
    ? periodosConSaldo.reduce((m, p) => (p.fecha_vencimiento > m ? p.fecha_vencimiento : m), '') || null
    : periodoElegido?.fecha_vencimiento || null
  const maxDias = esGeneral
    ? periodosConSaldo.reduce((t, p) => t + Math.floor(p.dias_disponible + 1e-6), 0)
    : periodoElegido && periodoElegido.dias_disponible > 0 ? periodoElegido.dias_disponible : null
  useEffect(() => { if (periodoSolicitud) setPeriodoSel(periodoSolicitud) }, [periodoSolicitud])
  // Elegir en la tarjeta un periodo con saldo también lo usa para la selección del calendario
  const elegirPeriodo = (id) => {
    setPeriodoSel(id)
    if (id === 'general' || periodosConSaldo.some((p) => p.id === id)) setPeriodoSolicitud(id)
  }

  // Tramos del calendario que corresponden a cada periodo (de un aniversario al siguiente), más el próximo
  const franjas = useMemo(() => {
    const orden = [...periodos].sort((a, b) => a.fecha_inicio.localeCompare(b.fecha_inicio))
    const hoy = toISO(new Date())
    const out = orden.map((p, i) => ({
      desde: p.fecha_inicio,
      hasta: diaAnterior(orden[i + 1]?.fecha_inicio || unAnioDespues(p.fecha_inicio)),
      color: colorPeriodo(p), nombre: p.nombre,
      // Un periodo anterior se deja de mostrar cuando ya no tiene días (o venció); el actual siempre se muestra
      visible: p.fecha_inicio <= hoy && (orden[i + 1]?.fecha_inicio || '9999') > hoy
        ? true : p.vigente && p.dias_disponible > 0,
    })).filter((x) => x.visible)
    const ultimo = orden[orden.length - 1]
    const inicioProximo = ultimo ? unAnioDespues(ultimo.fecha_inicio) : empleado?.fecha_ingreso && unAnioDespues(empleado.fecha_ingreso)
    if (inicioProximo) {
      out.push({ desde: inicioProximo, hasta: '9999-12-31', color: colorPeriodo({ numero: (ultimo?.numero || 0) + 1 }),
        nombre: `Periodo ${inicioProximo.slice(0, 4)} (próximo)` })
    }
    return out
  }, [periodos, empleado?.fecha_ingreso])
  const franjasDelAnio = franjas.filter((x) => x.desde <= `${anio}-12-31` && x.hasta >= `${anio}-01-01`)
  const franjasVisibles = franjas.filter((x) => !ocultos.includes(x.nombre))

  // Cumpleaños y aniversarios: en mi calendario se muestran según mis preferencias (Registros o menú Cumpleaños)
  const verCumples = !!usuarioId || user?.ver_cumpleanos !== false
  const verAnivs = !!usuarioId || user?.ver_aniversarios !== false
  const cumplesVisibles = useMemo(() => (calendario?.cumpleanos || [])
    .filter((c) => (c.tipo === 'aniversario' ? verAnivs : verCumples)), [calendario, verCumples, verAnivs])
  const calendarioVisible = useMemo(() => calendario && { ...calendario, cumpleanos: cumplesVisibles }, [calendario, cumplesVisibles])
  async function alternarEstimados(k) {
    const p = { ver_cumpleanos: user?.ver_cumpleanos !== false, ver_aniversarios: user?.ver_aniversarios !== false }
    p[k] = !p[k]
    try {
      await api('/estimados/preferencias', { method: 'PUT', body: p })
      await recargar()
    } catch (e) {
      setError(e.message)
    }
  }

  // Aniversario de ingreso en el año mostrado: resaltado (renueva el periodo de vacaciones) salvo que lo oculte
  const aniversario = useMemo(() => {
    const fi = empleado?.fecha_ingreso
    if (!fi || Number(fi.slice(0, 4)) >= anio) return null
    const [m, d] = [Number(fi.slice(5, 7)), Number(fi.slice(8, 10))]
    const dia = m === 2 && d === 29 && new Date(anio, 1, 29).getMonth() !== 1 ? 28 : d
    const anios = anio - Number(fi.slice(0, 4))
    return { fecha: toISO(new Date(anio, m - 1, dia)), titulo: `Aniversario: ${anios} año${anios === 1 ? '' : 's'} en la empresa · inicia el Periodo ${anio}` }
  }, [empleado?.fecha_ingreso, anio])

  // Vista previa de días laborales del rango seleccionado en el calendario
  useEffect(() => {
    setSelCalc(null)
    const vigente = periodoElegido || periodos.find((p) => p.vigente)
    if (!seleccion?.fin || soloLectura) return
    if (!vigente && !esGeneral) {
      api('/vacaciones/dias-laborales', {
        method: 'POST', body: { fecha_inicio: seleccion.inicio, fecha_fin: seleccion.fin, usuario_id: usuarioId },
      }).then((d) => setSelCalc({ ...d, errores: [] })).catch(() => {})
      return
    }
    api('/vacaciones/calcular', {
      method: 'POST',
      body: { periodo_id: esGeneral ? null : vigente.id, fecha_inicio: seleccion.inicio, fecha_fin: seleccion.fin, usuario_id: usuarioId },
    }).then(setSelCalc).catch(() => {})
  }, [seleccion, periodos, periodoSolicitud])

  // Esc cancela la selección de días y luego el resaltado (si no hay una ventana abierta)
  useEffect(() => {
    if ((!seleccion && !foco) || modal || lista) return
    const alPresionar = (e) => {
      if (e.key !== 'Escape') return
      if (seleccion) setSeleccion(null)
      else setFoco(null)
    }
    window.addEventListener('keydown', alPresionar)
    return () => window.removeEventListener('keydown', alPresionar)
  }, [seleccion, foco, modal, lista])

  const refrescar = () => {
    setModal(null)
    setSeleccion(null)
    cargar()
    cargarCalendario()
    window.dispatchEvent(new Event('pendientes:refrescar'))
  }

  async function accion(ruta, metodo = 'POST', confirmar) {
    if (confirmar && !window.confirm(confirmar)) return
    try {
      await api(ruta, { method: metodo })
      refrescar()
    } catch (e) {
      alert(e.message)
    }
  }

  const periodo = periodoSel === 'general' ? null : periodos.find((p) => p.id === periodoSel)
  const esPlanta = empleado?.rol === 'planta'
  // Periodos vigentes anteriores al actual con saldo: se pierden al cumplir 18 meses
  const vigentesConSaldo = periodos.filter((p) => p.vigente && p.dias_disponible > 0)
  const porVencer = vigentesConSaldo.length > 1 ? vigentesConSaldo[vigentesConSaldo.length - 1] : null
  const diasParaVencer = porVencer ? Math.ceil((parseISO(porVencer.fecha_vencimiento) - new Date()) / 864e5) : null

  const eventos = useMemo(() => eventosPorFecha(calendario), [calendario])
  const registros = useMemo(() => {
    const r = Object.fromEntries(Object.keys(CATEGORIAS).map((k) => [k, { dias: 0, aprobados: 0, pendientes: 0, horas: 0 }]))
    for (const evs of Object.values(eventos)) {
      for (const e of evs) {
        const k = e.cat === 'consulta_medica' ? 'consulta' : e.cat
        if (!r[k]) continue
        r[k].dias += 1
        if (e.estado === 'validado' || e.estado === 'registrada') r[k].aprobados += 1
        else if (e.estado === 'solicitado') r[k].pendientes += 1
      }
    }
    for (const pm of permisos) {
      const k = CATEGORIAS[pm.tipo] ? pm.tipo : 'otro_permiso'
      if (pm.fecha.startsWith(String(anio)) && r[k] && !pm.por_dias && pm.tipo !== 'home_office' && ['solicitado', 'validado'].includes(pm.estado)) {
        r[k].horas += pm.horas
      }
    }
    r.festivo.dias = (calendario?.festivos || []).length
    r.equipo.dias = equipos.filter((s) => s.estado !== 'cancelado' && s.fecha_inicio.slice(0, 4) <= String(anio) && s.fecha_fin.slice(0, 4) >= String(anio)).length
    r.cumpleanos.dias = cumplesVisibles.length
    return r
  }, [eventos, permisos, equipos, calendario, cumplesVisibles, anio])

  const base = periodo ? Math.max(periodo.horas_otorgadas, periodo.horas_total) : 0
  const pct = (h) => (base > 0 ? `${Math.max(0, (h / base) * 100)}%` : '0%')
  const aDias = (h) => (periodo ? h / periodo.horas_por_dia : 0)
  const diasLey = periodo ? aDias(periodo.horas_otorgadas) : 0
  // Ajuste negativo = días tomados antes del sistema (saldo capturado); positivo = días extra
  const tomadosAntes = periodo ? Math.max(0, -periodo.ajuste_horas) : 0
  const extra = periodo ? Math.max(0, periodo.ajuste_horas) : 0

  // Tarjeta del usuario: foto, tipo de usuario, puesto, ingreso, antigüedad, nómina, jefe y turno
  const perfil = empleado && (
    <div className="card ps-perfil">
      <div className="pf-cab">
        {usuarioId && <button className="icon-btn plain" onClick={() => navigate(-1)} title="Regresar"><ArrowLeft size={16} /></button>}
        <Avatar usuario={empleado} tam={48} />
        <div className="pf-datos">
          <div className="pf-nombre" title={empleado.nombre}>{empleado.nombre}</div>
          <div className="pf-puesto">{[empleado.puesto, empleado.departamento].filter(Boolean).join(' · ')}</div>
          <span className="chip pf-rol">{ROLES[empleado.rol]}{empleado.es_jefe && !esAdminFn(empleado) ? ' · Jefe' : ''}</span>
        </div>
      </div>
      <dl className="pf-lista">
        <dt>Ingreso</dt>
        <dd>
          {fmtFecha(empleado.fecha_ingreso, false)}
          <span className="muted"> · {empleado.antiguedad_anios > 0 ? `${empleado.antiguedad_anios} año(s)` : 'menos de 1 año'}</span>
        </dd>
        {empleado.fecha_nacimiento && <><dt>Cumpleaños</dt><dd>{diaMes(empleado.fecha_nacimiento)}</dd></>}
        {empleado.numero_empleado && <><dt>Nómina</dt><dd>{empleado.numero_empleado}</dd></>}
        {empleado.jefe_nombre ? <><dt>Jefe</dt><dd>{empleado.jefe_nombre}</dd></>
          : empleado.jefes_grupo_nombres?.length > 0 && <><dt>{empleado.subgrupo_nombre ? `Jefes (${empleado.subgrupo_nombre})` : 'Jefes del grupo'}</dt><dd>{empleado.jefes_grupo_nombres.join(', ')}</dd></>}
        {empleado.grupo_nombre && <><dt>Grupo</dt><dd>{empleado.grupo_nombre}</dd></>}
      </dl>
      <MiTurno usuarioId={usuarioId} incrustado />
    </div>
  )

  // Franja superior: usuario, saldo y registros del año
  const panel = (
    <div className={`panel-sup ${tab === 'calendario' ? 'oculto-movil' : ''}`}>
      {perfil}

      <div className="card ps-saldo">
        <div className="ps-cab">
          <span className="ps-titulo">Vacaciones</span>
          {periodos.length > 1 ? (
            <select className="ps-select" value={periodoSel ?? ''}
              onChange={(e) => elegirPeriodo(e.target.value === 'general' ? 'general' : Number(e.target.value))}>
              {hayGeneral && <option value="general">General</option>}
              {periodos.filter((p) => p.vigente).map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
              {periodos.some((p) => !p.vigente) && (
                <optgroup label="Vencidos">
                  {periodos.filter((p) => !p.vigente).map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
                </optgroup>
              )}
            </select>
          ) : periodo && <span className="muted">{periodo.nombre}</span>}
        </div>
        {periodoSel === 'general' ? (
          <>
            <div className="ps-numero"><b>{num(diasGeneral)}</b> días disponibles</div>
            <div className="ps-reparto">
              {periodosConSaldo.map((p, i) => (
                <div key={p.id} style={{ '--c': colorPeriodo(p) }}>
                  <i /> {p.nombre} <b>{num(p.dias_disponible)} d</b>
                  <span className="muted"> · vence {fmtFecha(p.fecha_vencimiento, false)}{i === 0 ? ' · se usa primero' : ''}</span>
                </div>
              ))}
            </div>
          </>
        ) : periodo ? (
          <>
            <div className="ps-numero" title={[
              `${num(diasLey)} días por antigüedad${esPlanta ? ' (de 12 h)' : ''}`,
              tomadosAntes > 0 && `${num(aDias(tomadosAntes))} tomados antes del sistema`,
              extra > 0 && `+${num(aDias(extra))} de ajuste`,
            ].filter(Boolean).join(' · ')}>
              <b>{num(periodo.dias_disponible)}</b> de {num(diasLey + aDias(extra))} días disponibles
            </div>
            <div className="barra delgada">
              <div className="c-disp" style={{ width: pct(periodo.horas_disponible) }} />
              <div className="c-borr" style={{ width: pct(periodo.horas_borrador) }} />
              <div className="c-soli" style={{ width: pct(periodo.horas_solicitado) }} />
              <div className="c-vali" style={{ width: pct(periodo.horas_validado) }} />
              <div className="c-antes" style={{ width: pct(tomadosAntes) }} />
              <div style={{ width: pct(periodo.horas_perdidas), background: 'var(--danger)' }} />
            </div>
            <div className="ps-cifras">
              <div><b>{num(periodo.dias_solicitado)}</b>por aprobar</div>
              <div><b>{num(periodo.dias_validado + aDias(tomadosAntes))}</b>tomados</div>
              <div><b>{fmtFecha(periodo.fecha_vencimiento, false)}</b>{periodo.vigente ? 'vencen' : 'vencieron'}</div>
            </div>
            {periodo.vigente ? (
              <div className={`ps-bloque ${periodo.bloque_cumplido ? 'ok' : ''}`}>
                {periodo.bloque_cumplido
                  ? `✓ Ya tomaste tus ${periodo.minimo_dias} días seguidos`
                  : `Recuerda tomar ${periodo.minimo_dias} días seguidos al menos una vez`}
              </div>
            ) : (
              <div className="ps-bloque vencido">
                {periodo.dias_perdidos > 0 ? `Periodo vencido: se perdieron ${num(periodo.dias_perdidos)} día(s)` : 'Periodo vencido'}
              </div>
            )}
          </>
        ) : (
          <div className="ps-pie" style={{ marginTop: 6 }}>Aún no tienes días: se generan al cumplir cada año de servicio.</div>
        )}
        {porVencer && (
          <div className="ps-bloque vencido" title="Después de 18 meses los días no usados se pierden">
            Usa antes del {fmtFecha(porVencer.fecha_vencimiento, false)} tus {num(porVencer.dias_disponible)} día(s) del {porVencer.nombre}
            {diasParaVencer !== null && ` (faltan ${diasParaVencer} días)`}
          </div>
        )}
      </div>

      <div className="card ps-registros">
        <PanelRegistros anio={anio} registros={registros} franjas={franjasDelAnio} foco={foco}
          visible={(k) => (['llegada_tarde', 'salida_temprana', 'salida_intermedia', 'home_office'].includes(k) ? permisoHabilitado(k)
            : k === 'otro_permiso' ? hayOtros
            : k === 'incapacidad' ? false
            : k === 'consulta' ? politica?.modulo_consultas !== false : k === 'cumpleanos' ? politica?.modulo_cumpleanos !== false : true)
            || (registros[k]?.dias || 0) > 0}
          ocultos={ocultos} onPeriodo={alternarPeriodo}
          onTodosPeriodos={(ver) => setOcultos(ver ? [] : franjasDelAnio.map((x) => x.nombre))}
          aniversario={aniversario} miCumple={(calendario?.cumpleanos || []).find((c) => c.propio && c.tipo !== 'aniversario')}
          verCumples={verCumples} verAnivs={verAnivs} onEstimados={usuarioId ? undefined : alternarEstimados}
          onFoco={(k) => setFoco((f) => (f === k ? null : k))}
          onAbrir={(k) => { setFoco(k === 'todas' ? null : k); setLista(k) }} />
      </div>
    </div>
  )

  return (
    <div className="vac-pagina">
      <div className="tabs">
        <button className={tab === 'resumen' ? 'activo' : ''} onClick={() => setTab('resumen')}>RESUMEN</button>
        <button className={tab === 'calendario' ? 'activo' : ''} onClick={() => setTab('calendario')}>CALENDARIO</button>
      </div>
      {panel}
      {error && <div className="alerta error">{error}</div>}

      <div className={`card cal-card ${tab === 'resumen' ? 'oculto-movil' : ''}`}>
        {!soloLectura && (
          <BarraSeleccion seleccion={seleccion} calc={selCalc} onLimpiar={() => setSeleccion(null)}
            periodos={periodosConSaldo} periodoId={periodoSolicitud} onPeriodo={setPeriodoSolicitud}
            hayGeneral={hayGeneral} diasGeneral={diasGeneral} maxDias={maxDias} fechaMax={fechaMax}
            homeOffice={permisoHabilitado('home_office')}
            permisos={tiposSede ? tiposSede.some((t) => t.clave !== 'home_office')
              : ['llegada_tarde', 'salida_temprana', 'salida_intermedia'].some(permisoHabilitado)}
            permisoPorDias={(tiposSede || []).some((t) => t.modalidad === 'dias' && t.clave !== 'home_office')}
            onVacaciones={() => setModal({ tipo: 'vac', inicial: { fecha_inicio: seleccion.inicio, fecha_fin: seleccion.fin || seleccion.inicio, periodo_id: esGeneral ? null : periodoSolicitud } })}
            onPermiso={() => setModal({ tipo: 'perm', fechaInicial: seleccion.inicio, fechaFinInicial: seleccion.fin || seleccion.inicio })}
            onHomeOffice={() => setModal({ tipo: 'perm', tipoPermiso: 'home_office', fechaInicial: seleccion.inicio, fechaFinInicial: seleccion.fin || seleccion.inicio })}
            onNuevaVacacion={periodosConSaldo.length > 0 ? () => setModal({ tipo: 'vac' }) : null}
            onNuevoPermiso={() => setModal({ tipo: 'perm' })}
            onEquipo={usuarioId ? null : () => setModal({ tipo: 'equipo', inicial: seleccion ? { fecha_inicio: seleccion.inicio, fecha_fin: seleccion.fin || seleccion.inicio } : null })} />
        )}
        <YearCalendar anio={anio} onAnio={setAnio} datos={calendarioVisible} seleccion={seleccion} compacto
          onSeleccion={soloLectura ? undefined : setSeleccion}
          onDia={(f) => setModal({ tipo: 'dia', fecha: f })}
          franjas={franjasVisibles} aniversario={verAnivs ? aniversario : null}
          foco={foco} />
      </div>

      {lista && (
        <ListaSolicitudes categoria={lista} anio={anio} vacaciones={vacaciones} permisos={permisos} consultas={consultas} equipos={equipos}
          festivos={calendario?.festivos || []} cumpleanos={cumplesVisibles} esAdmin={esAdmin} soloLectura={soloLectura} accion={accion}
          onVer={(i) => setModal({ tipo: 'ver', item: i })}
          onEditar={(i) => setModal({ tipo: i.cat === 'vacaciones' ? 'vac' : 'perm', item: i })}
          onConsulta={(i) => setModal({ tipo: 'consulta', item: i })}
          onEquipo={(i, que) => setModal({ tipo: que, salida: i })}
          onClose={() => setLista(null)} />
      )}
      {modal?.tipo === 'vac' && (
        <VacacionesModal periodos={periodos} usuarioId={usuarioId} empleado={empleado} solicitud={modal.item}
          inicial={modal.inicial}
          onClose={() => setModal(null)} onSaved={refrescar} />
      )}
      {modal?.tipo === 'perm' && (
        <PermisoModal usuario={empleado} tipoInicial={modal.tipoPermiso} permiso={modal.item} fechaInicial={modal.fechaInicial}
          tipos={tiposSede}
          fechaFinInicial={modal.fechaFinInicial}
          onClose={() => setModal(null)} onSaved={refrescar} />
      )}
      {modal?.tipo === 'ver' && <Detalle item={modal.item} onClose={() => setModal(null)} />}
      {modal?.tipo === 'equipo' && (
        <SalidaEquipoModal salida={modal.salida} inicial={modal.inicial} onClose={() => setModal(null)} onSaved={refrescar} />
      )}
      {modal?.tipo === 'formato' && <FormatoEquipo salida={modal.salida} onClose={() => setModal(null)} />}
      {modal?.tipo === 'dia' && (
        <EventosDia fecha={modal.fecha} eventos={eventos[modal.fecha] || []}
          festivo={(calendario?.festivos || []).find((x) => x.fecha === modal.fecha)?.nombre}
          descanso={(calendario?.no_laborables || []).includes(modal.fecha)}
          persona={usuarioId ? empleado?.nombre : null} onClose={() => setModal(null)}
          cumpleanos={(calendario?.cumpleanos || []).filter((c) => c.fecha === modal.fecha)}
          aniversario={aniversario?.fecha === modal.fecha ? aniversario.titulo : null} />
      )}
      {modal?.tipo === 'consulta' && (
        <DetalleConsulta consultaId={modal.item.detalle_clinico ? modal.item.id : null} resumen={modal.item}
          onClose={() => setModal(null)} />
      )}
    </div>
  )
}

/** Registros del año por categoría (clic: abre sus solicitudes) y leyenda de periodos y estados del calendario. */
function PanelRegistros({ anio, registros, franjas, foco, onFoco, onAbrir, ocultos, onPeriodo, onTodosPeriodos, aniversario, miCumple,
  verCumples = true, verAnivs = true, onEstimados, visible = () => true }) {
  const algunoVisible = franjas.some((x) => !ocultos.includes(x.nombre))
  // Solo las categorías con algo registrado en el año (vacaciones siempre)
  const cats = Object.entries(CATEGORIAS).filter(([k]) => k !== 'consulta_medica' && k !== 'aniversario' && visible(k)
    && (k === 'vacaciones' || (registros[k]?.dias || 0) > 0))
  const texto = (k, r) => {
    if (k === 'vacaciones' || k === 'home_office') return `${r.dias} día(s)${r.pendientes ? ` · ${r.pendientes} pend.` : ''}`
    if (k === 'consulta') return `${r.dias} consulta(s)`
    if (k === 'festivo') return `${r.dias} día(s)`
    if (k === 'cumpleanos') return `${r.dias} fecha(s)`
    if (k === 'equipo') return `${r.dias} solicitud(es)`
    return `${r.dias} · ${num(r.horas)} h`
  }
  return (
    <div className="registros">
      <div className="registros-cab">
        <b>Registros {anio}</b>
        <span className="muted">Toca una para marcarla en el calendario</span>
        {foco && <button type="button" className="btn btn-sm" onClick={() => onFoco(foco)}>Quitar marca</button>}
        <button type="button" className="btn btn-sm" onClick={() => onAbrir('todas')}>Mis solicitudes</button>
      </div>
      {cats.map(([k, c]) => (
        <div key={k} className="registro-fila">
          <button type="button" className={`registro ${foco === k ? 'activo' : ''}`} aria-pressed={foco === k}
            style={foco === k ? { borderColor: c.color, background: `${c.color}14` } : undefined}
            onClick={() => (k === 'equipo' ? onAbrir(k) : onFoco(k))} onDoubleClick={() => onAbrir(k)}>
            <span className="reg-icono" style={{ background: c.color }}><IconoCategoria cat={k} size={12} /></span>
            <span>{c.label}</span>
            <b>{texto(k, registros[k])}</b>
          </button>
          <button type="button" className="icon-btn plain" title={`Ver la lista: ${c.label}`} onClick={() => onAbrir(k)}>
            <Eye size={14} />
          </button>
        </div>
      ))}
      <div className="registros-leyenda">
        {franjas.map((x) => {
          const oculto = ocultos.includes(x.nombre)
          return (
            <button key={x.desde} type="button" className={`ley-franja ${oculto ? 'oculto' : ''}`} style={{ '--franja': x.color }}
              onClick={() => onPeriodo(x.nombre)} aria-pressed={!oculto}
              title={`${oculto ? 'Mostrar' : 'Ocultar'} el color del ${x.nombre} · del ${fmtFecha(x.desde, false)}${x.hasta < '9999' ? ` al ${fmtFecha(x.hasta, false)}` : ' en adelante'}`}>
              <i /> {x.nombre} {oculto ? <EyeOff size={11} /> : <Eye size={11} />}
            </button>
          )
        })}
        {franjas.length > 0 && (
          <button type="button" className="ley-todos" onClick={() => onTodosPeriodos(!algunoVisible)}>
            {algunoVisible ? 'Quitar colores de periodo' : 'Ver colores de periodo'}
          </button>
        )}
        {aniversario && (onEstimados ? (
          <button type="button" className={`ley-especial aniv ${verAnivs ? '' : 'oculto'}`} aria-pressed={verAnivs}
            onClick={() => onEstimados('ver_aniversarios')}
            title={`${aniversario.titulo}\n${verAnivs ? 'Ocultar' : 'Mostrar'} los aniversarios en tu calendario (el tuyo y los de tus compañeros)`}>
            <IconoCategoria cat="aniversario" size={11} /> Aniversario {diaMes(aniversario.fecha)} {verAnivs ? <Eye size={11} /> : <EyeOff size={11} />}
          </button>
        ) : (
          <span className="ley-especial aniv" title={aniversario.titulo}>
            <IconoCategoria cat="aniversario" size={11} /> Aniversario {diaMes(aniversario.fecha)}
          </span>
        ))}
        {miCumple && (onEstimados ? (
          <button type="button" className={`ley-especial cumple ${verCumples ? '' : 'oculto'}`} aria-pressed={verCumples}
            onClick={() => onEstimados('ver_cumpleanos')}
            title={`${verCumples ? 'Ocultar' : 'Mostrar'} los cumpleaños en tu calendario (el tuyo y los de tus compañeros)`}>
            <IconoCategoria cat="cumpleanos" size={11} /> Tu cumpleaños {diaMes(miCumple.fecha)} {verCumples ? <Eye size={11} /> : <EyeOff size={11} />}
          </button>
        ) : (
          <span className="ley-especial cumple"><IconoCategoria cat="cumpleanos" size={11} /> Tu cumpleaños {diaMes(miCumple.fecha)}</span>
        ))}
        <span className="ley-estados">
          <i style={estiloEvento('vacaciones', 'validado')}>A</i> Aprobado
          <i style={estiloEvento('vacaciones', 'solicitado')}>P</i> Pendiente
          <i style={estiloEvento('vacaciones', 'borrador')}>B</i> Borrador
        </span>
      </div>
    </div>
  )
}

/** Ventana con las solicitudes de una categoría de Registros (o todas), con filtros y acciones. */
function ListaSolicitudes({ categoria, anio, vacaciones, permisos, consultas, equipos = [], festivos, cumpleanos, esAdmin, soloLectura, accion,
  onVer, onEditar, onConsulta, onEquipo, onClose }) {
  const [estado, setEstado] = useState('')
  const [cat, setCat] = useState(categoria === 'todas' ? '' : categoria)
  const [soloAnio, setSoloAnio] = useState(true)

  const items = useMemo(() => {
    const vs = vacaciones.map((v) => ({ ...v, cat: 'vacaciones', orden: v.fecha_inicio, fin: v.fecha_fin }))
    const ps = permisos.map((p) => ({ ...p, cat: CATEGORIAS[p.tipo] ? p.tipo : 'otro_permiso', orden: p.fecha, fin: p.fecha_fin || p.fecha }))
    const cs = consultas.map((c) => ({ ...c, cat: 'consulta', orden: `${c.fecha}T${c.hora_inicio}`, fin: c.fecha }))
    const es = equipos.map((s) => ({ ...s, cat: 'equipo', orden: s.fecha_inicio, fin: s.fecha_fin }))
    return [...vs, ...ps, ...cs, ...es]
      .filter((i) => !estado || i.estado === estado)
      .filter((i) => !cat || (cat === 'permisos' ? !['vacaciones', 'consulta', 'equipo'].includes(i.cat)
        : cat === 'incapacidad' ? i.cat === 'consulta' && i.incapacidad : i.cat === cat))
      .filter((i) => !soloAnio || (i.orden.slice(0, 4) <= String(anio) && i.fin.slice(0, 4) >= String(anio)))
      .sort((a, b) => b.orden.localeCompare(a.orden))
  }, [vacaciones, permisos, consultas, equipos, estado, cat, soloAnio, anio])

  if (cat === 'cumpleanos') {
    const hoy = hoyISO()
    const proximo = cumpleanos.find((c) => c.fecha >= hoy)
    return (
      <Modal titulo={`Cumpleaños y aniversarios ${anio}`} onClose={onClose}
        pie={<><a className="btn" href="/cumpleanos">Preferencias</a><button className="btn" onClick={onClose}>Cerrar</button></>}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Cumpleaños y aniversarios del personal de tu sede.</p>
        {cumpleanos.length === 0 && <div className="muted">Aún no hay cumpleaños ni aniversarios que mostrar.</div>}
        <div className="lista-cumples">
          {cumpleanos.map((c) => (
            <div key={`${c.tipo}-${c.usuario_id}`} className={`cumple-fila ${c.fecha === hoy ? 'hoy' : ''} ${c === proximo && c.fecha !== hoy ? 'proximo' : ''}`}>
              <Avatar usuario={{ id: c.usuario_id, nombre: c.nombre, tiene_foto: c.tiene_foto }} tam={30} />
              <div className="cf-datos"><b>{c.nombre}</b>
                <span className="muted"> · {c.tipo === 'aniversario' ? `${c.anios} año${c.anios === 1 ? '' : 's'} en la empresa` : 'cumpleaños'}</span></div>
              <span className="cf-fecha">{c.fecha === hoy ? (c.tipo === 'aniversario' ? '🏅 ¡Hoy!' : '🎂 ¡Hoy!') : diaMes(c.fecha)}</span>
            </div>
          ))}
        </div>
      </Modal>
    )
  }

  if (cat === 'festivo') {
    return (
      <Modal titulo={`Días festivos ${anio}`} onClose={onClose} pie={<button className="btn" onClick={onClose}>Cerrar</button>}>
        <table className="tabla">
          <tbody>
            {festivos.length === 0 && <tr><td className="muted">Sin festivos registrados.</td></tr>}
            {festivos.map((f) => <tr key={f.fecha}><td style={{ width: 130 }}>{fmtFecha(f.fecha)}</td><td>{f.nombre}</td></tr>)}
          </tbody>
        </table>
      </Modal>
    )
  }

  const titulo = cat ? (CATEGORIAS[cat]?.label || 'Permisos') : 'Todas las solicitudes'
  return (
    <Modal ancho titulo={titulo} onClose={onClose} pie={<button className="btn" onClick={onClose}>Cerrar</button>}>
      <div className="lista-cab">
        <select value={cat} onChange={(e) => setCat(e.target.value)}>
          <option value="">Cualquier categoría</option>
          <option value="vacaciones">Vacaciones</option>
          <option value="permisos">Todos los permisos</option>
          {Object.entries(TIPOS_PERMISO_SOLICITABLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          <option value="otro_permiso">Otros permisos</option>
          <option value="consulta">Consultas médicas</option>
          <option value="incapacidad">Incapacidades</option>
          {equipos.length > 0 && <option value="equipo">Salida de equipo</option>}
        </select>
        <select value={estado} onChange={(e) => setEstado(e.target.value)}>
          <option value="">Cualquier estado</option>
          {Object.entries(ESTADOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label className="checkbox"><input type="checkbox" checked={soloAnio} onChange={(e) => setSoloAnio(e.target.checked)} /> Solo {anio}</label>
      </div>
      <div className="lista-sol">
        {items.length === 0 && <div className="muted" style={{ padding: 20, textAlign: 'center' }}>No hay solicitudes.</div>}
        {items.map((i) => (
          <div className="item-sol" key={`${i.cat === 'vacaciones' ? 'v' : i.cat === 'consulta' ? 'c' : i.cat === 'equipo' ? 'e' : 'p'}${i.id}`}>
            <div className="info">
              <div className="titulo">
                <span className="reg-icono" style={{ background: CATEGORIAS[i.cat]?.color, marginRight: 6 }}><IconoCategoria cat={i.cat} size={12} /></span>
                {i.cat === 'vacaciones' ? 'Vacaciones' : i.cat === 'equipo' ? `Salida de equipo · ${i.marca} ${i.modelo}` : i.cat === 'consulta'
                  ? <span className="fila" style={{ gap: 6 }}><Stethoscope size={16} color="#00796b" /> Consulta médica</span>
                  : nombreTipo(i)}
              </div>
              <div className="detalle">
                {i.cat === 'vacaciones'
                  ? `${fmtFecha(i.fecha_inicio)} - ${fmtFecha(i.fecha_fin)} (${i.dias_habiles} d) · ${i.periodo_nombre}`
                  : i.cat === 'equipo'
                    ? `${fmtFecha(i.fecha_inicio)} - ${fmtFecha(i.fecha_fin)} · SN ${i.serie}`
                  : i.cat === 'consulta'
                    ? `${fmtFecha(i.fecha)} ${hhmm(i.hora_inicio)}${i.hora_fin ? ` - ${hhmm(i.hora_fin)}` : ''} · Atendió: ${i.medico_nombre || 'Servicio médico'}`
                    : i.por_dias || i.tipo === 'home_office'
                      ? `${fmtFecha(i.fecha)} - ${fmtFecha(i.fecha_fin || i.fecha)} (${i.dias ?? '—'} d laborales)`
                      : `${fmtFecha(i.fecha)} ${hhmm(i.hora_inicio)} - ${hhmm(i.hora_fin)} (${num(i.horas)} h)`}
              </div>
              {i.aprobador_nombre && (
                <div className="detalle muted" style={{ marginTop: 2, fontSize: 12 }}>
                  {i.estado === 'validado' || i.estado === 'rechazado' ? 'Revisó' : 'Aprueba'}: {i.revisado_por_nombre || i.aprobador_nombre}
                </div>
              )}
              {i.estado === 'rechazado' && i.motivo_rechazo && (
                <div className="detalle" style={{ color: 'var(--danger)' }}>Motivo: {i.motivo_rechazo}</div>
              )}
            </div>
            <div className="acciones">
              {i.cat === 'equipo' ? (
                <>
                  <span className={`pill ${claseSituacion(i)}`}>{i.situacion}</span>
                  <button className="icon-btn" title="Ver formato F-630-03" onClick={() => onEquipo(i, 'formato')}><FileText size={16} /></button>
                  {i.estado === 'borrador' && (
                    <>
                      <button className="icon-btn" title="Editar" onClick={() => onEquipo(i, 'equipo')}><Pencil size={16} /></button>
                      <button className="icon-btn verde" title="Firmar y enviar" onClick={() => onEquipo(i, 'equipo')}><Send size={16} /></button>
                      <button className="icon-btn rojo" title="Eliminar" onClick={() => accion(`/equipos/${i.id}`, 'DELETE', '¿Eliminar este borrador?')}><Trash2 size={16} /></button>
                    </>
                  )}
                  {['solicitado', 'validado'].includes(i.estado) && !i.salida_registrada && (
                    <button className="icon-btn rojo" title="Cancelar solicitud"
                      onClick={() => accion(`/equipos/${i.id}/cancelar`, 'POST', '¿Cancelar esta solicitud de salida de equipo?')}><Ban size={16} /></button>
                  )}
                </>
              ) : i.cat === 'consulta' ? (
                <>
                  {i.incapacidad
                    ? <span className={`pill ${i.incapacidad.estado}`}>Incapacidad · {ESTADOS_INCAPACIDAD[i.incapacidad.estado]}</span>
                    : <span className="pill consulta">Servicio médico</span>}
                  <button className="icon-btn" title="Ver lo que registró el médico" onClick={() => onConsulta(i)}><Eye size={16} /></button>
                </>
              ) : (
                <>
                  <span className={`pill ${i.estado}`}>{ESTADOS[i.estado]}</span>
                  <Acciones item={i} esAdmin={esAdmin} soloLectura={soloLectura} onVer={() => onVer(i)} onEditar={() => onEditar(i)}
                    accion={accion} />
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  )
}

function BarraSeleccion({ seleccion, calc, periodos, periodoId, onPeriodo, hayGeneral, diasGeneral, maxDias, fechaMax, onLimpiar,
  homeOffice = true, permisos = true, permisoPorDias = false,
  onVacaciones, onPermiso, onHomeOffice, onNuevaVacacion, onNuevoPermiso, onEquipo }) {
  // Periodo del que se tomarán los días (General: primero el más antiguo)
  const selectorPeriodo = periodos.length > 0 && (
    <div className="sel-periodos" role="radiogroup" aria-label="Periodo vacacional">
      {hayGeneral && (
        <button type="button" role="radio" aria-checked={periodoId === 'general'}
          className={`sel-periodo ${periodoId === 'general' ? 'activo' : ''}`} style={{ '--c': 'var(--primary)' }}
          onClick={() => onPeriodo('general')} title="Suma tus periodos y descuenta primero los días del más antiguo">
          <i /> General · {num(diasGeneral)} d
        </button>
      )}
      {periodos.map((p) => (
        <button key={p.id} type="button" role="radio" aria-checked={p.id === periodoId}
          className={`sel-periodo ${p.id === periodoId ? 'activo' : ''}`} style={{ '--c': colorPeriodo(p) }}
          onClick={() => onPeriodo(p.id)} title={`Vence el ${fmtFecha(p.fecha_vencimiento, false)}`}>
          <i /> {p.nombre} · {num(p.dias_disponible)} d
        </button>
      ))}
    </div>
  )
  if (!seleccion) {
    return (
      <div className="barra-sel vacia">
        <MousePointerClick size={16} />
        <span>Marca en el calendario el <b>primer</b> y el <b>último</b> día que necesitas. Clic derecho en un día para ver qué hay.</span>
        <div className="espacio" />
        {selectorPeriodo}
        <span className="acciones-rapidas">
          {onNuevaVacacion && <button className="btn btn-sm btn-primary" onClick={onNuevaVacacion}><TreePalm size={14} /> Pedir vacaciones</button>}
          {permisos && <button className="btn btn-sm" onClick={onNuevoPermiso}><Clock size={14} /> Pedir permiso</button>}
          {onEquipo && <button className="btn btn-sm" onClick={onEquipo}><Laptop size={14} /> Salida de equipo</button>}
        </span>
      </div>
    )
  }
  const general = periodoId === 'general'
  const periodoSel = periodos.find((p) => p.id === periodoId)
  const sinSaldo = !periodoSel && !general
  const reparto = calc?.reparto || []
  const fin = seleccion.fin || seleccion.inicio
  const naturales = Math.round((parseISO(fin) - parseISO(seleccion.inicio)) / 864e5) + 1
  const unDia = naturales === 1
  // Tope solo para vacaciones: días disponibles del periodo y fecha de vencimiento
  const excede = seleccion.fin && calc && maxDias !== null && calc.dias_habiles > Math.floor(maxDias + 1e-6)
    ? `Para vacaciones tienes máximo ${Math.floor(maxDias + 1e-6)} días laborales`
    : seleccion.fin && fechaMax && fin > fechaMax ? `Para vacaciones, a más tardar el ${fmtFecha(fechaMax, false)}` : null
  const errorVac = excede || calc?.errores[0]
  return (
    <div className="barra-sel con-seleccion">
      <b>{fmtFecha(seleccion.inicio)}{!unDia && ` → ${fmtFecha(fin)}`}</b>
      <span className="muted">
        {!seleccion.fin
          ? `Elige el último día…${maxDias ? ` (vacaciones: máximo ${Math.floor(maxDias + 1e-6)} días laborales${general ? ' entre tus periodos' : ` del ${periodoSel?.nombre}`}${fechaMax ? `, a más tardar el ${fmtFecha(fechaMax, false)}` : ''})` : ''}`
          : `${naturales} día(s) naturales`}
        {calc && seleccion.fin && ` · ${calc.dias_habiles} laborales`}
        {reparto.length > 1 && ` (${reparto.map((t) => `${t.dias} del ${t.periodo_nombre}`).join(' + ')})`}
      </span>
      {seleccion.fin && errorVac && (
        <span style={{ color: 'var(--danger)', fontSize: 12 }}>{errorVac}</span>
      )}
      <div className="espacio" />
      {selectorPeriodo}
      <button className="btn btn-sm btn-primary" onClick={onVacaciones}
        disabled={!seleccion.fin || !calc || !!errorVac || sinSaldo}
        title={sinSaldo ? 'No tienes días de vacaciones disponibles' : errorVac}>
        <TreePalm size={14} /> Solicitar vacaciones
      </button>
      {homeOffice && <button className="btn btn-sm" onClick={onHomeOffice} disabled={!seleccion.fin}><Laptop size={14} /> Home office</button>}
      {permisos && <button className="btn btn-sm" onClick={onPermiso}
        title={unDia ? undefined : 'Un permiso por cada día laboral seleccionado'}><Clock size={14} /> Solicitar permiso</button>}
      {onEquipo && <button className="btn btn-sm" onClick={onEquipo} disabled={!seleccion.fin}
        title="Sacar un equipo de cómputo de la empresa en estas fechas"><Laptop size={14} /> Salida de equipo</button>}
      <button className="icon-btn plain" title="Cancelar selección (Esc)" onClick={onLimpiar}><X size={16} /></button>
      <kbd className="tecla" title="Presiona Esc para cancelar la selección">Esc</kbd>
    </div>
  )
}

function Acciones({ item, esAdmin, soloLectura, onVer, onEditar, accion }) {
  const base = item.cat === 'vacaciones' ? `/vacaciones/${item.id}` : `/permisos/${item.id}`
  if (soloLectura) return <button className="icon-btn" title="Ver detalle" onClick={onVer}><Eye size={16} /></button>
  return (
    <>
      <button className="icon-btn" title="Ver detalle" onClick={onVer}><Eye size={16} /></button>
      {item.estado === 'borrador' && (
        <>
          <button className="icon-btn" title="Editar" onClick={onEditar}><Pencil size={16} /></button>
          <button className="icon-btn verde" title="Firmar y enviar" onClick={onEditar}><Send size={16} /></button>
          <button className="icon-btn rojo" title="Eliminar"
            onClick={() => accion(base, 'DELETE', '¿Eliminar este borrador?')}><Trash2 size={16} /></button>
        </>
      )}
      {(item.estado === 'solicitado' || (esAdmin && item.estado === 'validado')) && (
        <button className="icon-btn rojo" title="Cancelar solicitud"
          onClick={() => accion(`${base}/cancelar`, 'POST', '¿Cancelar esta solicitud?')}><Ban size={16} /></button>
      )}
    </>
  )
}

function Detalle({ item, onClose }) {
  const vac = item.cat === 'vacaciones'
  const filas = vac
    ? [['Periodo', item.periodo_nombre], ['Desde', fmtFecha(item.fecha_inicio)], ['Hasta', fmtFecha(item.fecha_fin)],
       ['Días laborales', item.dias_habiles], ['Horas', num(item.horas)], ['Comentario', item.comentario]]
    : [['Tipo', nombreTipo(item)], ...(item.por_dias
      ? [['Desde', fmtFecha(item.fecha)], ['Hasta', fmtFecha(item.fecha_fin || item.fecha)], ['Días laborales', item.dias]]
      : [['Fecha', fmtFecha(item.fecha)], ['Horario', `${hhmm(item.hora_inicio)} - ${hhmm(item.hora_fin)}`], ['Horas', num(item.horas)]]),
       ['Departamento', item.departamento], ['Tiempo en nómina', TIPOS_NOMINA[item.tipo_nomina]],
       ['Motivo', item.motivo], ['Observaciones', item.observaciones]]
  filas.push(['Jefe que aprueba', item.aprobador_nombre || 'Administración'])
  filas.push(['Estado', ESTADOS[item.estado]])
  if (item.revisado_por_nombre) filas.push(['Revisado por', `${item.revisado_por_nombre} · ${item.fecha_revision?.slice(0, 16).replace('T', ' ')}`])
  if (item.motivo_rechazo) filas.push(['Motivo de rechazo', item.motivo_rechazo])
  const [firma, setFirma] = useState(null)
  useEffect(() => {
    if (item.tiene_firma) api(`/${vac ? 'vacaciones' : 'permisos'}/${item.id}/firma`).then((r) => setFirma(r.firma)).catch(() => {})
  }, [item.id])
  return (
    <Modal titulo={vac ? 'Solicitud de vacaciones' : 'Permiso'} onClose={onClose}
      pie={<button className="btn" onClick={onClose}>Cerrar</button>}>
      <table className="tabla">
        <tbody>
          {filas.map(([k, v]) => <tr key={k}><td className="muted" style={{ width: 160 }}>{k}</td><td>{v || '—'}</td></tr>)}
          {item.pasos?.length > 0 && (
            <tr><td className="muted">Aprobación</td><td><PasosCadena pasos={item.pasos} /></td></tr>
          )}
          <tr>
            <td className="muted">Firma</td>
            <td>{firma ? <img className="firma-img" src={firma} alt="Firma del solicitante" /> : <span className="muted">Sin firma</span>}</td>
          </tr>
        </tbody>
      </table>
    </Modal>
  )
}
