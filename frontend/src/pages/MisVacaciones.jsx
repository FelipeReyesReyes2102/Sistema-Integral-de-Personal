import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Ban, ChevronDown, Clock, Eye, Laptop, MousePointerClick, Pencil, Send, Stethoscope, Trash2, TreePalm, X,
} from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import Modal from '../components/Modal'
import PermisoModal from '../components/PermisoModal'
import VacacionesModal from '../components/VacacionesModal'
import YearCalendar from '../components/YearCalendar'
import {
  CATEGORIAS, esAdmin as esAdminFn, ESTADOS, ROLES, TIPOS_NOMINA, TIPOS_PERMISO, TIPOS_PERMISO_SOLICITABLES, eventosPorFecha, fmtFecha, hhmm, num,
  parseISO,
} from '../utils'
import EventosDia from '../components/EventosDia'
import MiTurno from '../components/MiTurno'
import DetalleConsulta from '../components/DetalleConsulta'

export default function MisVacaciones({ usuarioId }) {
  const { user } = useAuth()
  const [empleado, setEmpleado] = useState(usuarioId ? null : user)
  const [periodos, setPeriodos] = useState([])
  const [periodoSel, setPeriodoSel] = useState(null)
  const [vacaciones, setVacaciones] = useState([])
  const [permisos, setPermisos] = useState([])
  const [consultas, setConsultas] = useState([])
  const [anio, setAnio] = useState(new Date().getFullYear())
  const [calendario, setCalendario] = useState(null)
  const [filtroEstado, setFiltroEstado] = useState('')
  const [filtroCat, setFiltroCat] = useState('')
  const [tab, setTab] = useState('resumen')
  const [menuNueva, setMenuNueva] = useState(false)
  const [modal, setModal] = useState(null) // {tipo: 'vac'|'perm'|'ver', item, tipoPermiso, inicial}
  const [seleccion, setSeleccion] = useState(null) // {inicio, fin} elegido en el calendario
  const [selCalc, setSelCalc] = useState(null)
  const [foco, setFoco] = useState(null) // categoría resaltada en el calendario
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const esAdmin = esAdminFn(user)
  const soloLectura = !!usuarioId && !esAdmin // jefe consultando a su personal
  const q = usuarioId ? { usuario_id: usuarioId } : undefined

  useEffect(() => {
    if (usuarioId) api(`/usuarios/${usuarioId}`).then(setEmpleado).catch((e) => setError(e.message))
  }, [usuarioId])

  const cargar = useCallback(async () => {
    try {
      const [ps, vs, pm, cs] = await Promise.all([
        api('/periodos', { query: q }), api('/vacaciones', { query: q }), api('/permisos', { query: q }),
        api('/consultas', { query: q }).catch(() => []),
      ])
      setPeriodos(ps)
      setVacaciones(vs)
      setPermisos(pm)
      setConsultas(cs)
      setPeriodoSel((sel) => (sel && ps.some((p) => p.id === sel) ? sel : (ps.find((p) => p.vigente) || ps[0])?.id ?? null))
    } catch (e) {
      setError(e.message)
    }
  }, [usuarioId])

  const cargarCalendario = useCallback(() => {
    api('/calendario', { query: { anio, ...q } }).then(setCalendario).catch((e) => setError(e.message))
  }, [anio, usuarioId])

  useEffect(() => { cargar() }, [cargar])
  useEffect(() => { cargarCalendario() }, [cargarCalendario])

  // Vista previa de días laborales del rango seleccionado en el calendario
  useEffect(() => {
    setSelCalc(null)
    const vigente = periodos.find((p) => p.vigente && p.horas_disponible > 0) || periodos.find((p) => p.vigente)
    if (!seleccion?.fin || soloLectura) return
    if (!vigente) {
      api('/vacaciones/dias-laborales', {
        method: 'POST', body: { fecha_inicio: seleccion.inicio, fecha_fin: seleccion.fin, usuario_id: usuarioId },
      }).then((d) => setSelCalc({ ...d, errores: [] })).catch(() => {})
      return
    }
    api('/vacaciones/calcular', {
      method: 'POST',
      body: { periodo_id: vigente.id, fecha_inicio: seleccion.inicio, fecha_fin: seleccion.fin, usuario_id: usuarioId },
    }).then(setSelCalc).catch(() => {})
  }, [seleccion, periodos])

  // Esc cancela la selección de días (si no hay una ventana abierta)
  useEffect(() => {
    if (!seleccion || modal) return
    const alPresionar = (e) => { if (e.key === 'Escape') setSeleccion(null) }
    window.addEventListener('keydown', alPresionar)
    return () => window.removeEventListener('keydown', alPresionar)
  }, [seleccion, modal])

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

  const periodo = periodos.find((p) => p.id === periodoSel)
  const esPlanta = empleado?.rol === 'planta'
  // Periodos vigentes anteriores al actual con saldo: se pierden al cumplir 18 meses
  const vigentesConSaldo = periodos.filter((p) => p.vigente && p.dias_disponible > 0)
  const porVencer = vigentesConSaldo.length > 1 ? vigentesConSaldo[vigentesConSaldo.length - 1] : null
  const diasParaVencer = porVencer ? Math.ceil((parseISO(porVencer.fecha_vencimiento) - new Date()) / 864e5) : null

  const items = useMemo(() => {
    const vs = vacaciones.map((v) => ({ ...v, cat: 'vacaciones', orden: v.fecha_inicio }))
    const ps = permisos.map((p) => ({ ...p, cat: p.tipo, orden: p.fecha }))
    const cs = consultas.map((c) => ({ ...c, cat: 'consulta', orden: `${c.fecha}T${c.hora_inicio}` }))
    return [...vs, ...ps, ...cs]
      .filter((i) => !filtroEstado || i.estado === filtroEstado)
      .filter((i) => !filtroCat || (filtroCat === 'permisos' ? !['vacaciones', 'consulta'].includes(i.cat) : i.cat === filtroCat))
      .sort((a, b) => b.orden.localeCompare(a.orden))
  }, [vacaciones, permisos, consultas, filtroEstado, filtroCat])

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
      if (pm.fecha.startsWith(String(anio)) && r[pm.tipo] && pm.tipo !== 'home_office' && ['solicitado', 'validado'].includes(pm.estado)) {
        r[pm.tipo].horas += pm.horas
      }
    }
    r.festivo.dias = (calendario?.festivos || []).length
    return r
  }, [eventos, permisos, calendario, anio])

  function enfocar(cat) {
    const nuevo = foco === cat ? null : cat
    setFoco(nuevo)
    setFiltroCat(nuevo && nuevo !== 'festivo' ? nuevo : '')
  }

  const pct = (h) => (periodo && periodo.horas_total > 0 ? `${Math.max(0, (h / periodo.horas_total) * 100)}%` : '0%')

  function nueva(tipo, tipoPermiso) {
    setMenuNueva(false)
    setModal({ tipo, tipoPermiso })
  }

  const cabecera = usuarioId && empleado && (
    <div className="card" style={{ marginBottom: 12, padding: '12px 16px' }}>
      <div className="fila">
        <button className="icon-btn plain" onClick={() => navigate(-1)} title="Regresar"><ArrowLeft size={18} /></button>
        <div>
          <div style={{ fontWeight: 500, fontSize: 16 }}>{empleado.nombre}</div>
          <div className="muted">
            #{empleado.numero_empleado} · {empleado.puesto || ROLES[empleado.rol]} · ingreso {fmtFecha(empleado.fecha_ingreso, false)}
            {` · ${empleado.antiguedad_anios} año(s)`}
            {empleado.grupo_nombre && ` · ${empleado.grupo_nombre}`}{empleado.turno_nombre && ` · Turno ${empleado.turno_nombre}`}
            {empleado.jefe_nombre && ` · Jefe: ${empleado.jefe_nombre}`}
          </div>
        </div>
      </div>
    </div>
  )

  // Franja superior compacta: turno, saldo, registros del año y nueva solicitud
  const panel = (
    <div className={`panel-sup ${tab === 'calendario' ? 'oculto-movil' : ''}`}>
      <MiTurno usuarioId={usuarioId} compacto />

      <div className="card ps-saldo">
        <div className="ps-cab">
          <span className="ps-titulo">Vacaciones</span>
          {periodos.length > 1 ? (
            <select className="ps-select" value={periodoSel ?? ''} onChange={(e) => setPeriodoSel(Number(e.target.value))}>
              {periodos.map((p) => <option key={p.id} value={p.id}>{p.nombre}{!p.vigente ? ' (vencido)' : ''}</option>)}
            </select>
          ) : periodo && <span className="muted">{periodo.nombre}</span>}
        </div>
        {periodo ? (
          <>
            <div className="ps-numero"><b>{num(periodo.dias_disponible)}</b> días disponibles</div>
            <div className="barra delgada"
              title={`Disponible ${num(periodo.dias_disponible)} d · Borrador ${num(periodo.dias_borrador)} d · Solicitado ${num(periodo.dias_solicitado)} d · Validado ${num(periodo.dias_validado)} d`}>
              <div className="c-disp" style={{ width: pct(periodo.horas_disponible) }} />
              <div className="c-borr" style={{ width: pct(periodo.horas_borrador) }} />
              <div className="c-soli" style={{ width: pct(periodo.horas_solicitado) }} />
              <div className="c-vali" style={{ width: pct(periodo.horas_validado) }} />
              <div style={{ width: pct(periodo.horas_perdidas), background: 'var(--danger)' }} />
            </div>
            <div className="ps-pie">
              {num(periodo.dias_total)} d{esPlanta ? ' de 12 h' : ''}
              {periodo.dias_solicitado > 0 && ` · ${num(periodo.dias_solicitado)} solicitado(s)`}
              {periodo.dias_validado > 0 && ` · ${num(periodo.dias_validado)} tomado(s)`}
              {` · vence ${fmtFecha(periodo.fecha_vencimiento, false)}`}
            </div>
            {periodo.vigente ? (
              <div className={`ps-bloque ${periodo.bloque_cumplido ? 'ok' : ''}`}>
                {periodo.bloque_cumplido
                  ? `✓ Bloque de ${periodo.minimo_dias} días seguidos cumplido`
                  : `Pendiente: un bloque de ${periodo.minimo_dias} días seguidos`}
              </div>
            ) : (
              <div className="ps-bloque vencido">
                Venció el {fmtFecha(periodo.fecha_vencimiento, false)}
                {periodo.dias_perdidos > 0 ? `; se perdieron ${num(periodo.dias_perdidos)} día(s)` : ''}
              </div>
            )}
            {periodo.ajuste_horas !== 0 && (
              <div className="ps-pie">Ajuste: {num(periodo.ajuste_horas)} h {periodo.nota_ajuste && `(${periodo.nota_ajuste})`}</div>
            )}
          </>
        ) : (
          <div className="ps-pie" style={{ marginTop: 6 }}>Aún no tienes días: se generan al cumplir cada año de servicio.</div>
        )}
      </div>

      <div className="card ps-registros">
        <PanelRegistros anio={anio} registros={registros} foco={foco} onFoco={enfocar} />
      </div>

      {!soloLectura && (
        <div className="ps-acciones dropdown">
          <button className="btn btn-primary" onClick={() => setMenuNueva(!menuNueva)}>
            Nueva solicitud <ChevronDown size={16} />
          </button>
          {menuNueva && (
            <div className="dropdown-menu derecha">
              <button onClick={() => nueva('vac')}><TreePalm size={16} /> Vacaciones</button>
              <button onClick={() => nueva('perm', 'llegada_tarde')}><Clock size={16} /> Llegada tarde</button>
              <button onClick={() => nueva('perm', 'salida_temprana')}><Clock size={16} /> Salida temprana</button>
              <button onClick={() => nueva('perm', 'salida_intermedia')}><Clock size={16} /> Salida durante la jornada</button>
              <button onClick={() => nueva('perm', 'home_office')}><Laptop size={16} /> Home office</button>
            </div>
          )}
        </div>
      )}
    </div>
  )

  return (
    <>
      <div className="tabs">
        <button className={tab === 'resumen' ? 'activo' : ''} onClick={() => setTab('resumen')}>RESUMEN</button>
        <button className={tab === 'calendario' ? 'activo' : ''} onClick={() => setTab('calendario')}>CALENDARIO</button>
      </div>
      {cabecera}
      {panel}
      {porVencer && (
        <div className={`alerta warn ${tab === 'calendario' ? 'oculto-movil' : ''}`} style={{ marginTop: 0, marginBottom: 12 }}>
          <b>{num(porVencer.dias_disponible)} día(s)</b> del {porVencer.nombre} vencen el{' '}
          <b>{fmtFecha(porVencer.fecha_vencimiento, false)}</b>
          {diasParaVencer !== null && ` (en ${diasParaVencer} días)`}. Después de 18 meses se pierden; úsalos primero.
        </div>
      )}

      <div className={`card cal-card ${tab === 'resumen' ? 'oculto-movil' : ''}`}>
        {!soloLectura && (
          <BarraSeleccion seleccion={seleccion} calc={selCalc} onLimpiar={() => setSeleccion(null)}
            onVacaciones={() => setModal({ tipo: 'vac', inicial: { fecha_inicio: seleccion.inicio, fecha_fin: seleccion.fin || seleccion.inicio } })}
            onPermiso={() => setModal({ tipo: 'perm', fechaInicial: seleccion.inicio })}
            onHomeOffice={() => setModal({ tipo: 'perm', tipoPermiso: 'home_office', fechaInicial: seleccion.inicio, fechaFinInicial: seleccion.fin || seleccion.inicio })} />
        )}
        <YearCalendar anio={anio} onAnio={setAnio} datos={calendario} seleccion={seleccion}
          onSeleccion={soloLectura ? undefined : setSeleccion}
          foco={foco} onFoco={enfocar} onDia={(f) => setModal({ tipo: 'dia', fecha: f })} />
      </div>

      <div className={`card lista-card ${tab === 'calendario' ? 'oculto-movil' : ''}`}>
        <div className="lista-cab">
          <b>{usuarioId ? 'Solicitudes' : 'Mis solicitudes'}</b>
          <div className="espacio" />
          <select value={filtroEstado} onChange={(e) => setFiltroEstado(e.target.value)}>
            <option value="">Cualquier estado</option>
            {Object.entries(ESTADOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={filtroCat} onChange={(e) => setFiltroCat(e.target.value)}>
            <option value="">Cualquier categoría</option>
            <option value="vacaciones">Vacaciones</option>
            <option value="permisos">Todos los permisos</option>
            {Object.entries(TIPOS_PERMISO_SOLICITABLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            <option value="consulta">Consultas médicas</option>
          </select>
        </div>
        {error && <div className="alerta error">{error}</div>}
        <div className="lista-sol">
          {items.length === 0 && <div className="muted" style={{ padding: 20, textAlign: 'center' }}>No hay solicitudes.</div>}
          {items.map((i) => (
            <div className="item-sol" key={`${i.cat === 'vacaciones' ? 'v' : 'p'}${i.id}`}>
              <div className="info">
                <div className="titulo">
                  <i className="punto" style={{ background: CATEGORIAS[i.cat]?.color }} />
                  {i.cat === 'vacaciones' ? 'Vacaciones' : i.cat === 'consulta'
                    ? <span className="fila" style={{ gap: 6 }}><Stethoscope size={16} color="#00796b" /> Consulta médica</span>
                    : TIPOS_PERMISO[i.tipo]}
                </div>
                <div className="detalle">
                  {i.cat === 'vacaciones'
                    ? `${fmtFecha(i.fecha_inicio)} - ${fmtFecha(i.fecha_fin)} (${i.dias_habiles} d) · ${i.periodo_nombre}`
                    : i.cat === 'consulta'
                      ? `${fmtFecha(i.fecha)} ${hhmm(i.hora_inicio)}${i.hora_fin ? ` - ${hhmm(i.hora_fin)}` : ''} · Atendió: ${i.medico_nombre || 'Servicio médico'}`
                      : i.tipo === 'home_office'
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
                {i.cat === 'consulta' ? (
                  <>
                    <span className="pill consulta">Servicio médico</span>
                    <button className="icon-btn" title="Ver lo que registró el médico" onClick={() => setModal({ tipo: 'consulta', item: i })}><Eye size={16} /></button>
                  </>
                ) : (<>
                <span className={`pill ${i.estado}`}>{ESTADOS[i.estado]}</span>
                <Acciones item={i} esAdmin={esAdmin} soloLectura={soloLectura} onVer={() => setModal({ tipo: 'ver', item: i })}
                  onEditar={() => setModal({ tipo: i.cat === 'vacaciones' ? 'vac' : 'perm', item: i })}
                  accion={accion} />
                </>)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {modal?.tipo === 'vac' && (
        <VacacionesModal periodos={periodos} usuarioId={usuarioId} empleado={empleado} solicitud={modal.item}
          inicial={modal.inicial}
          onClose={() => setModal(null)} onSaved={refrescar} />
      )}
      {modal?.tipo === 'perm' && (
        <PermisoModal usuario={empleado} tipoInicial={modal.tipoPermiso} permiso={modal.item} fechaInicial={modal.fechaInicial}
          fechaFinInicial={modal.fechaFinInicial}
          onClose={() => setModal(null)} onSaved={refrescar} />
      )}
      {modal?.tipo === 'ver' && <Detalle item={modal.item} onClose={() => setModal(null)} />}
      {modal?.tipo === 'dia' && (
        <EventosDia fecha={modal.fecha} eventos={eventos[modal.fecha] || []}
          festivo={(calendario?.festivos || []).find((x) => x.fecha === modal.fecha)?.nombre}
          descanso={(calendario?.no_laborables || []).includes(modal.fecha)}
          persona={usuarioId ? empleado?.nombre : null} onClose={() => setModal(null)} />
      )}
      {modal?.tipo === 'consulta' && (
        <DetalleConsulta consultaId={modal.item.detalle_clinico ? modal.item.id : null} resumen={modal.item}
          onClose={() => setModal(null)} />
      )}
    </>
  )
}

/** Registros del año por categoría; al hacer clic se resaltan en el calendario y se filtra la lista. */
function PanelRegistros({ anio, registros, foco, onFoco }) {
  const texto = (k, r) => {
    if (k === 'vacaciones') return `${r.dias} día(s)${r.pendientes ? ` · ${r.pendientes} pendiente(s)` : ''}`
    if (k === 'home_office') return `${r.dias} día(s)${r.pendientes ? ` · ${r.pendientes} pendiente(s)` : ''}`
    if (k === 'consulta') return `${r.dias} consulta(s)`
    if (k === 'festivo') return `${r.dias} día(s)`
    return `${r.dias} · ${num(r.horas)} h`
  }
  return (
    <div className="registros">
      <div className="registros-cab">
        <b>Registros {anio}</b>
        <span className="muted">Clic para resaltarlos en el calendario</span>
        {foco && <button type="button" className="btn btn-sm" onClick={() => onFoco(foco)}>Mostrar todo</button>}
      </div>
      {Object.entries(CATEGORIAS).filter(([k]) => k !== 'consulta_medica').map(([k, c]) => (
        <button key={k} type="button" className={`registro ${foco === k ? 'activo' : ''}`} onClick={() => onFoco(k)}
          style={foco === k ? { borderColor: c.color, background: `${c.color}12` } : undefined}>
          <i style={{ background: c.color }} />
          <span>{c.label}</span>
          <b>{texto(k, registros[k])}</b>
        </button>
      ))}
    </div>
  )
}

function BarraSeleccion({ seleccion, calc, onLimpiar, onVacaciones, onPermiso, onHomeOffice }) {
  if (!seleccion) {
    return (
      <div className="barra-sel vacia">
        <MousePointerClick size={16} /> Selecciona en el calendario el primer y el último día para pedir vacaciones, home office o un permiso.
      </div>
    )
  }
  const fin = seleccion.fin || seleccion.inicio
  const naturales = Math.round((parseISO(fin) - parseISO(seleccion.inicio)) / 864e5) + 1
  const unDia = naturales === 1
  return (
    <div className="barra-sel">
      <b>{fmtFecha(seleccion.inicio)}{!unDia && ` → ${fmtFecha(fin)}`}</b>
      <span className="muted">
        {!seleccion.fin ? 'Elige el último día…' : `${naturales} día(s) naturales`}
        {calc && seleccion.fin && ` · ${calc.dias_habiles} laborales`}
      </span>
      {calc && seleccion.fin && calc.errores.length > 0 && (
        <span style={{ color: 'var(--danger)', fontSize: 12 }}>{calc.errores[0]}</span>
      )}
      <div className="espacio" />
      <button className="btn btn-sm btn-primary" onClick={onVacaciones} disabled={!seleccion.fin}>
        <TreePalm size={14} /> Solicitar vacaciones
      </button>
      <button className="btn btn-sm" onClick={onHomeOffice} disabled={!seleccion.fin}><Laptop size={14} /> Home office</button>
      {unDia && <button className="btn btn-sm" onClick={onPermiso}><Clock size={14} /> Solicitar permiso</button>}
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
    : [['Tipo', TIPOS_PERMISO[item.tipo]], ['Fecha', fmtFecha(item.fecha)],
       ['Horario', `${hhmm(item.hora_inicio)} - ${hhmm(item.hora_fin)}`], ['Horas', num(item.horas)],
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
          <tr>
            <td className="muted">Firma</td>
            <td>{firma ? <img className="firma-img" src={firma} alt="Firma del solicitante" /> : <span className="muted">Sin firma</span>}</td>
          </tr>
        </tbody>
      </table>
    </Modal>
  )
}
