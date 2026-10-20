import { useEffect, useState } from 'react'
import { Clock3, Pencil, Plus, Save, Scale, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { num, textoLimite } from '../utils'

const JORNADA_NUEVA = { nombre: '', horas_dia: 8, bloque_minimo: 6, usa_ciclo_grupo: false, activo: true, descuento: '', por_horas: false, minimo_horas: 1 }
const GENERACION = {
  aniversario: 'Al cumplir cada año de servicio (aniversario)',
  calendario: 'Cada 1 de enero (año calendario; el primero proporcional)',
  mensual: 'Mes a mes durante el año de servicio (proporcional)',
}
const DESCUENTO = { '': 'Como la sede', horas: 'Horas', dias: 'Días' }

/** Política de vacaciones y permisos de la sede activa, sus tipos de jornada y las reglas vigentes que resultan. */
export default function ConfigPolitica() {
  const [pol, setPol] = useState(null)
  const [form, setForm] = useState(null)
  const [jornada, setJornada] = useState(null) // en edición
  const [msg, setMsg] = useState(null)

  const aplicar = (p) => {
    setPol(p)
    const { meses_vigencia, equivalencia_horas, dias_anticipacion, modulo_consultas, modulo_cumpleanos,
      generacion_dias, aprobacion_gh_vacaciones, aprobacion_gh_permisos } = p
    setForm({ meses_vigencia, equivalencia_horas, dias_anticipacion, modulo_consultas, modulo_cumpleanos,
      generacion_dias, aprobacion_gh_vacaciones, aprobacion_gh_permisos })
  }
  const cargar = () => api('/politica').then(aplicar).catch((e) => setMsg({ ok: false, t: e.message }))
  useEffect(() => {
    cargar()
    window.addEventListener('politica:refrescar', cargar)  // al cambiar los tipos de permiso
    return () => window.removeEventListener('politica:refrescar', cargar)
  }, [])
  if (!pol || !form) return <div className="card">{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>

  const set = (k, conv = (v) => v) => (e) => setForm({ ...form, [k]: conv(e.target.type === 'checkbox' ? e.target.checked : e.target.value) })

  async function guardar() {
    setMsg(null)
    try {
      aplicar(await api('/politica', { method: 'PUT', body: { ...form, meses_vigencia: Number(form.meses_vigencia), dias_anticipacion: Number(form.dias_anticipacion) } }))
      setMsg({ ok: true, t: `Política de ${pol.sede_nombre} guardada. Los saldos se recalculan automáticamente.` })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  async function guardarJornada() {
    setMsg(null)
    try {
      const body = { ...jornada, horas_dia: Number(jornada.horas_dia), bloque_minimo: Number(jornada.bloque_minimo),
        descuento: jornada.descuento || null, minimo_horas: Number(jornada.minimo_horas) || 1 }
      if (jornada.id) await api(`/jornadas/${jornada.id}`, { method: 'PUT', body })
      else await api('/jornadas', { method: 'POST', body })
      setJornada(null)
      cargar()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  async function borrarJornada(j) {
    if (!window.confirm(`¿Eliminar la jornada ${j.nombre}?`)) return
    try {
      await api(`/jornadas/${j.id}`, { method: 'DELETE' })
      cargar()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  const setJ = (k) => (e) => setJornada({ ...jornada, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const año1 = pol.tabla[0]?.dias ?? 12

  return (
    <div className="card">
      <h3 className="fila" style={{ gap: 8, marginBottom: 6 }}><Scale size={18} /> Política de vacaciones y permisos · {pol.sede_nombre}</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Las vacaciones se cuentan en <b>días hábiles</b>: no cuentan fines de semana, descansos del ciclo ni festivos de la sede.
      </p>

      <div className="pol-grid">
        <label className="campo">Vigencia de los días (meses)
          <input type="number" min={1} max={60} value={form.meses_vigencia} onChange={set('meses_vigencia')} />
          <span className="muted" style={{ fontSize: 11 }}>Después se pierden los días no usados.</span>
        </label>
        <label className="campo">Anticipación para pedir vacaciones (días)
          <input type="number" min={0} max={90} value={form.dias_anticipacion} onChange={set('dias_anticipacion')} />
        </label>
        <label className="campo full">Cuándo se generan los días
          <select value={form.generacion_dias} onChange={set('generacion_dias')}>
            {Object.entries(GENERACION).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <span className="muted" style={{ fontSize: 11 }}>Si a alguien se le planean vacaciones sin saldo, se le descuentan de los próximos días que se generen.</span>
        </label>
        <div className="campo full">
          <span>Aprobación</span>
          <label className="checkbox"><input type="checkbox" checked={form.aprobacion_gh_vacaciones} onChange={set('aprobacion_gh_vacaciones')} /> Vacaciones: primero el jefe y después GH</label>
          <label className="checkbox"><input type="checkbox" checked={form.aprobacion_gh_permisos} onChange={set('aprobacion_gh_permisos')} /> Permisos: primero el jefe y después GH</label>
          <span className="muted" style={{ fontSize: 11 }}>Sin marcar, basta con la aprobación del jefe. GH siempre puede validar directamente.</span>
        </div>
        <label className="campo full">Cómo se otorgan los días de la tabla (por defecto)
          <select value={String(form.equivalencia_horas)} onChange={set('equivalencia_horas', (v) => v === 'true')}>
            <option value="true">Equivalencia en horas: días de la tabla × 8 h, que cada jornada consume según sus horas</option>
            <option value="false">Días completos: cada día de la tabla es un día de la jornada del empleado</option>
          </select>
        </label>
        <div className="campo">
          <span>Módulos</span>
          <label className="checkbox"><input type="checkbox" checked={form.modulo_consultas} onChange={set('modulo_consultas')} /> Servicio médico (consultas)</label>
          <label className="checkbox"><input type="checkbox" checked={form.modulo_cumpleanos} onChange={set('modulo_cumpleanos')} /> Cumpleaños en el calendario</label>
        </div>
      </div>
      <div className="fila" style={{ marginTop: 10 }}>
        <div className="espacio" />
        <button className="btn btn-primary" onClick={guardar}><Save size={15} /> Guardar política</button>
      </div>

      <h4 className="fila" style={{ gap: 6, margin: '18px 0 8px', fontSize: 14 }}><Clock3 size={16} /> Tipos de jornada</h4>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Jornada</th><th>Horas por día</th><th>Bloque mínimo</th><th>Días hábiles</th><th>Saldo en</th><th>Por horas</th><th>Empleados</th><th /></tr></thead>
          <tbody>
            {pol.jornadas.map((j) => (
              <tr key={j.id} style={{ opacity: j.activo ? 1 : 0.5 }}>
                <td><b>{j.nombre}</b>{!j.activo && <span className="muted"> (inactiva)</span>}</td>
                <td>{j.horas_dia} h</td>
                <td>{j.bloque_minimo} días seguidos</td>
                <td>{j.usa_ciclo_grupo ? 'Según el ciclo del grupo' : 'Lunes a viernes'}</td>
                <td>{DESCUENTO[j.descuento || ''] }{!j.descuento && <span className="muted"> ({pol.equivalencia_horas ? 'horas' : 'días'})</span>}</td>
                <td>{j.por_horas ? `Sí · mín. ${j.minimo_horas} h` : 'No'}</td>
                <td>{j.empleados}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="icon-btn" title="Editar" onClick={() => setJornada({ ...j })}><Pencil size={14} /></button>{' '}
                  <button className="icon-btn rojo" title="Eliminar" onClick={() => borrarJornada(j)}><Trash2 size={14} /></button>
                </td>
              </tr>
            ))}
            {jornada && (
              <tr className="fila-edicion">
                <td><input value={jornada.nombre} onChange={setJ('nombre')} placeholder="Ej. Planta 10 h" /></td>
                <td><input type="number" min={1} max={24} value={jornada.horas_dia} onChange={setJ('horas_dia')} /></td>
                <td><input type="number" min={1} max={30} value={jornada.bloque_minimo} onChange={setJ('bloque_minimo')} /></td>
                <td>
                  <select value={String(jornada.usa_ciclo_grupo)} onChange={(e) => setJornada({ ...jornada, usa_ciclo_grupo: e.target.value === 'true' })}>
                    <option value="false">Lunes a viernes</option>
                    <option value="true">Ciclo del grupo</option>
                  </select>
                </td>
                <td>
                  <select value={jornada.descuento || ''} onChange={setJ('descuento')}>
                    {Object.entries(DESCUENTO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td>
                  <label className="checkbox"><input type="checkbox" checked={jornada.por_horas} onChange={setJ('por_horas')} /> Permitir</label>
                  {jornada.por_horas && <span className="fila" style={{ gap: 4, marginTop: 4 }}>mín. <input type="number" style={{ width: 56 }} min={1} max={23} value={jornada.minimo_horas} onChange={setJ('minimo_horas')} /> h</span>}
                </td>
                <td><label className="checkbox"><input type="checkbox" checked={jornada.activo} onChange={setJ('activo')} /> Activa</label></td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="icon-btn verde" title="Guardar" onClick={guardarJornada}><Save size={14} /></button>{' '}
                  <button className="icon-btn plain" title="Cancelar" onClick={() => setJornada(null)}><X size={14} /></button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {!jornada && <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => setJornada({ ...JORNADA_NUEVA })}><Plus size={14} /> Agregar jornada</button>}
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}

      <h4 style={{ margin: '18px 0 8px', fontSize: 14 }}>Reglas vigentes</h4>
      <ul className="reglas-vigentes">
        {pol.jornadas.filter((j) => j.activo).map((j) => (
          <li key={j.id}>
            <b>{j.nombre}:</b> 1 día = {j.horas_dia} h; días hábiles {j.usa_ciclo_grupo ? 'según el ciclo del grupo (p. ej. 4×4)' : 'de lunes a viernes'}.
            {' '}Año 1 = {(j.descuento ? j.descuento === 'horas' : pol.equivalencia_horas)
              ? <>{año1} × 8 h = {año1 * 8} h ÷ {j.horas_dia} = <b>{num((año1 * 8) / j.horas_dia)} días</b></>
              : <b>{año1} días</b>}.
            {' '}Bloque obligatorio: al menos una vez por periodo <b>{j.bloque_minimo} días seguidos</b>.
          </li>
        ))}
        <li>Los días se generan {pol.generacion_dias === 'calendario' ? 'cada 1 de enero (el primer año, proporcional a los meses trabajados)'
          : pol.generacion_dias === 'mensual' ? 'mes a mes durante cada año de servicio' : 'al cumplir cada año de servicio'} según la tabla de antigüedad{pol.tabla_propia ? ' de la sede' : ' (heredada de la sede principal)'} y se pierden a los <b>{pol.meses_vigencia} meses</b>.</li>
        <li>Mientras no se haya solicitado el bloque obligatorio, no se pueden pedir días sueltos que dejen el saldo por debajo de él.</li>
        {pol.dias_anticipacion > 0 && <li>Las vacaciones se piden con al menos <b>{pol.dias_anticipacion} día(s)</b> de anticipación.</li>}
        <li>Permisos habilitados: {pol.permisos_tipos?.length ? pol.permisos_tipos.map((t) => `${t.nombre}${t.limite_cantidad ? ` (${textoLimite(t)})` : ''}`).join(', ') : 'ninguno'}.</li>
        <li>Estados: Borrador → Solicitado → {pol.aprobacion_gh_vacaciones ? 'Aprobado por el jefe → ' : ''}Validado / Rechazado. Borrador y Solicitado ya apartan saldo.</li>
        {pol.jornadas.some((j) => j.por_horas) && <li>Vacaciones por horas: {pol.jornadas.filter((j) => j.por_horas).map((j) => `${j.nombre} (mín. ${j.minimo_horas} h)`).join(', ')}.</li>}
      </ul>
    </div>
  )
}
