import { useEffect, useState } from 'react'
import { ArrowRight, Mail, RefreshCw, Save } from 'lucide-react'
import { api } from '../api'
import { fmtFecha } from '../utils'

const DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']

/** Configuración de la rotación de turnos entre grupos (administrador). */
export default function RotacionTurnos({ onCambio }) {
  const [estado, setEstado] = useState(null)
  const [form, setForm] = useState(null)
  const [msg, setMsg] = useState(null)
  const [ocupado, setOcupado] = useState(false)

  const aplicar = (e) => {
    setEstado(e)
    setForm({
      activo: e.activo, fecha_inicio: e.fecha_inicio || '', semanas: e.semanas, turnos_orden: e.turnos_orden,
      turno_unico_id: e.turno_unico_id || '', aviso_activo: e.aviso_activo, aviso_hora: e.aviso_hora,
      grupos: e.grupos.map((g) => ({ grupo_id: g.id, en_rotacion: g.en_rotacion, turno_inicial_id: g.turno_inicial_id || '' })),
    })
  }
  const cargar = () => api('/rotacion').then(aplicar).catch((e) => setMsg({ ok: false, t: e.message }))
  useEffect(() => { cargar() }, [])

  if (!form) return <div className="card" style={{ marginTop: 20 }}>{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>

  const turnoNombre = (id) => estado.turnos.find((t) => t.id === Number(id))?.nombre || '—'
  const set = (k, conv = (v) => v) => (e) => setForm({ ...form, [k]: conv(e.target.type === 'checkbox' ? e.target.checked : e.target.value) })
  const toggleTurno = (id) => setForm({
    ...form, turnos_orden: form.turnos_orden.includes(id) ? form.turnos_orden.filter((x) => x !== id) : [...form.turnos_orden, id],
  })
  const setGrupo = (gid, k, v) => setForm({ ...form, grupos: form.grupos.map((g) => (g.grupo_id === gid ? { ...g, [k]: v } : g)) })
  const diaCambio = form.fecha_inicio ? DIAS[(new Date(`${form.fecha_inicio}T12:00`).getDay() + 6) % 7] : null
  const afectados = estado.grupos.filter((g) => form.grupos.find((x) => x.grupo_id === g.id)?.en_rotacion || g.en_rotacion)
    .reduce((s, g) => s + g.miembros, 0)

  async function guardar() {
    if (estado.activo && !form.activo && !window.confirm(
      `Al desactivar la rotación, ${afectados} empleado(s) de los grupos quedarán en el turno "${turnoNombre(form.turno_unico_id)}". ¿Continuar?`)) return
    setMsg(null)
    setOcupado(true)
    try {
      const r = await api('/rotacion', {
        method: 'PUT',
        body: {
          ...form, fecha_inicio: form.fecha_inicio || null, semanas: Number(form.semanas), aviso_hora: Number(form.aviso_hora),
          turno_unico_id: form.turno_unico_id ? Number(form.turno_unico_id) : null,
          grupos: form.grupos.map((g) => ({ ...g, turno_inicial_id: g.turno_inicial_id ? Number(g.turno_inicial_id) : null })),
        },
      })
      aplicar(r)
      setMsg({ ok: true, t: `Guardado. ${r.usuarios_actualizados} empleado(s) cambiaron de turno.` })
      onCambio?.()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado(false)
    }
  }

  async function avisarAhora() {
    if (!window.confirm('¿Enviar ahora por correo a cada empleado su turno de la próxima semana?')) return
    setOcupado(true)
    try {
      const r = await api('/rotacion/avisos', { method: 'POST' })
      setMsg(r.motivo ? { ok: false, t: r.motivo }
        : { ok: r.errores === 0, t: `Avisos enviados: ${r.enviados} · con error: ${r.errores} · sin correo: ${r.omitidos}. Revisa "Últimos envíos" en Configuración.` })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado(false)
    }
  }

  return (
    <div className="card" style={{ marginTop: 20 }}>
      <div className="fila" style={{ marginBottom: 4 }}>
        <h3 className="fila" style={{ gap: 8 }}><RefreshCw size={18} /> Rotación de turnos</h3>
        <span className={`pill ${estado.activo ? 'validado' : 'borrador'}`}>{estado.activo ? 'Activa' : 'Desactivada'}</span>
        <span className="muted" style={{ fontSize: 13 }}>{estado.descripcion}</span>
      </div>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Con la rotación activa, los grupos seleccionados cambian de turno automáticamente cada periodo. Al desactivarla,
        todo el personal de los grupos queda en un solo turno.
      </p>

      <div className="cfg-grid">
        <div className="of">
          <div className="of-caja"><span className="of-et">Rotación de turnos</span>
            <select value={String(form.activo)} onChange={set('activo', (v) => v === true || v === 'true')}>
              <option value="true">Activada</option>
              <option value="false">Desactivada (un solo turno)</option>
            </select>
          </div>
        </div>
        <div className="of">
          <div className="of-caja"><span className="of-et">{form.activo ? 'Turno si se desactiva' : 'Turno único para todos'}</span>
            <select value={form.turno_unico_id} onChange={set('turno_unico_id')}>
              <option value="">Selecciona…</option>
              {estado.turnos.map((t) => <option key={t.id} value={t.id}>{t.nombre} ({t.hora_entrada} - {t.hora_salida})</option>)}
            </select>
          </div>
          {!form.activo && <span className="of-ayuda">Al guardar, {afectados} empleado(s) de los grupos quedarán en este turno.</span>}
        </div>

        {form.activo && (
          <>
            <div className="of full">
              <span className="of-ayuda" style={{ fontSize: 12 }}>Turnos que rotan (en este orden):</span>
              <div className="fila">
                {estado.turnos.map((t) => (
                  <label key={t.id} className="checkbox">
                    <input type="checkbox" checked={form.turnos_orden.includes(t.id)} onChange={() => toggleTurno(t.id)} />
                    {t.nombre} <span className="muted">({t.hora_entrada}-{t.hora_salida})</span>
                  </label>
                ))}
              </div>
              {form.turnos_orden.length > 0 && (
                <div className="fila" style={{ gap: 6, fontSize: 13 }}>
                  {form.turnos_orden.map((id, i) => <span key={id} className="fila" style={{ gap: 6 }}>{i > 0 && <ArrowRight size={14} />}<span className="chip">{turnoNombre(id)}</span></span>)}
                  <ArrowRight size={14} /> <span className="muted">(se repite)</span>
                </div>
              )}
            </div>
            <div className="of">
              <div className="of-caja"><span className="of-et">Inicio de la rotación</span>
                <input type="date" value={form.fecha_inicio} onChange={set('fecha_inicio')} />
              </div>
              <span className="of-ayuda">{diaCambio ? `Los cambios de turno serán cada ${diaCambio}` : 'Día en que empieza el primer periodo'}</span>
            </div>
            <div className="of">
              <div className="of-caja"><span className="of-et">Cambiar de turno cada</span>
                <select value={form.semanas} onChange={set('semanas', Number)}>
                  {[1, 2, 3, 4, 6, 8].map((n) => <option key={n} value={n}>{n === 1 ? '1 semana' : `${n} semanas`}</option>)}
                </select>
              </div>
            </div>

            <div className="full">
              <div className="tabla-wrap">
                <table className="tabla">
                  <thead><tr><th>Rota</th><th>Grupo</th><th>Empleados</th><th>Turno en el primer periodo</th><th>Turno actual</th></tr></thead>
                  <tbody>
                    {estado.grupos.map((g) => {
                      const f = form.grupos.find((x) => x.grupo_id === g.id)
                      return (
                        <tr key={g.id}>
                          <td><input type="checkbox" style={{ width: 'auto' }} checked={f.en_rotacion} onChange={(e) => setGrupo(g.id, 'en_rotacion', e.target.checked)} /></td>
                          <td><span className="punto" style={{ background: g.color }} />{g.nombre}</td>
                          <td>{g.miembros}</td>
                          <td>
                            <select style={{ width: 180 }} disabled={!f.en_rotacion} value={f.turno_inicial_id}
                              onChange={(e) => setGrupo(g.id, 'turno_inicial_id', e.target.value)}>
                              <option value="">—</option>
                              {form.turnos_orden.map((id) => <option key={id} value={id}>{turnoNombre(id)}</option>)}
                            </select>
                          </td>
                          <td>{g.turno_actual || <span className="muted">—</span>}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="of">
              <div className="of-caja"><span className="of-et">Aviso semanal por correo</span>
                <select value={String(form.aviso_activo)} onChange={set('aviso_activo', (v) => v === true || v === 'true')}>
                  <option value="true">Enviar cada viernes el turno de la semana siguiente</option>
                  <option value="false">No enviar</option>
                </select>
              </div>
              <span className="of-ayuda">Usa la configuración de correo de Configuración → Avisos por correo.{estado.ultimo_aviso ? ` Último envío: ${fmtFecha(estado.ultimo_aviso)}.` : ''}</span>
            </div>
            <div className="of">
              <div className="of-caja"><span className="of-et">Hora del envío (viernes)</span>
                <select value={form.aviso_hora} onChange={set('aviso_hora', Number)} disabled={!form.aviso_activo}>
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
                </select>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="fila" style={{ marginTop: 16 }}>
        <button className="btn btn-primary" onClick={guardar} disabled={ocupado}><Save size={15} /> Guardar</button>
        <div className="espacio" />
        {estado.activo && <button className="btn" onClick={avisarAhora} disabled={ocupado}><Mail size={15} /> Enviar aviso de turnos ahora</button>}
      </div>
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}

      {estado.activo && estado.vista_previa.length > 0 && (
        <>
          <h4 style={{ margin: '20px 0 8px', fontSize: 14 }}>Próximos periodos</h4>
          <div className="tabla-wrap">
            <table className="tabla">
              <thead>
                <tr><th>Periodo</th>{estado.grupos.filter((g) => g.en_rotacion).map((g) => <th key={g.id}>{g.nombre}</th>)}</tr>
              </thead>
              <tbody>
                {estado.vista_previa.map((p, i) => (
                  <tr key={p.desde} style={i === 0 ? { background: 'var(--primary-light)' } : undefined}>
                    <td style={{ whiteSpace: 'nowrap' }}>{fmtFecha(p.desde)} → {fmtFecha(p.hasta)}{i === 0 && <span className="chip" style={{ marginLeft: 6 }}>actual</span>}</td>
                    {estado.grupos.filter((g) => g.en_rotacion).map((g) => <td key={g.id}><b>{p.grupos[g.id] || '—'}</b></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
