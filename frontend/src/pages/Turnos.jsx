import { useEffect, useState } from 'react'
import { CalendarClock, Pencil, Plus, Trash2, X } from 'lucide-react'
import { api } from '../api'
import Modal from '../components/Modal'
import RotacionTurnos from '../components/RotacionTurnos'
import SedeActual from '../components/SedeActual'
import { fmtFecha, hhmm, hoyISO } from '../utils'

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
const DIAS_CORTOS = ['L', 'M', 'X', 'J', 'V', 'S', 'D']
const VACIO = { nombre: '', hora_entrada: '07:00', hora_salida: '19:00', horas_jornada: 12, descripcion: '', activo: true, dias: [], especiales: [] }
const especialNuevo = (f) => ({ nombre: 'Short Friday', fecha_inicio: hoyISO(), fecha_fin: '', dias: [4], cada_semanas: 1,
  hora_entrada: f.hora_entrada, hora_salida: '15:00', activo: true })

const cadaTxt = (n) => (n === 1 ? 'todas las semanas' : n === 2 ? 'una semana sí y una no' : `cada ${n} semanas`)

export default function Turnos() {
  const [lista, setLista] = useState([])
  const [form, setForm] = useState(null)
  const [error, setError] = useState('')
  const cargar = () => api('/turnos').then(setLista)
  useEffect(() => { cargar() }, [])

  const abrir = (t) => setForm({
    ...t, hora_entrada: hhmm(t.hora_entrada), hora_salida: hhmm(t.hora_salida),
    dias: (t.dias || []).map((d) => ({ ...d, hora_entrada: hhmm(d.hora_entrada), hora_salida: hhmm(d.hora_salida) })),
    especiales: (t.especiales || []).map((e) => ({ ...e, fecha_fin: e.fecha_fin || '', hora_entrada: hhmm(e.hora_entrada), hora_salida: hhmm(e.hora_salida) })),
  })

  async function guardar() {
    setError('')
    const body = {
      ...form, horas_jornada: Number(form.horas_jornada),
      especiales: form.especiales.map((e) => ({ ...e, fecha_fin: e.fecha_fin || null, cada_semanas: Number(e.cada_semanas) })),
    }
    try {
      if (form.id) await api(`/turnos/${form.id}`, { method: 'PUT', body })
      else await api('/turnos', { method: 'POST', body })
      setForm(null)
      cargar()
    } catch (e) {
      setError(e.message)
    }
  }

  async function borrar(t) {
    if (!window.confirm(`¿Eliminar el turno ${t.nombre}? Los empleados quedarán sin turno.`)) return
    await api(`/turnos/${t.id}`, { method: 'DELETE' }).catch((e) => alert(e.message))
    cargar()
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  // Horario por día: si el día no tiene horario propio, usa el general
  const delDia = (i) => form.dias.find((d) => d.dia === i)
  const togglePropio = (i) => setForm({
    ...form,
    dias: delDia(i) ? form.dias.filter((d) => d.dia !== i)
      : [...form.dias, { dia: i, hora_entrada: form.hora_entrada, hora_salida: form.hora_salida }].sort((a, b) => a.dia - b.dia),
  })
  const setDia = (i, k) => (e) => setForm({ ...form, dias: form.dias.map((d) => (d.dia === i ? { ...d, [k]: e.target.value } : d)) })
  // Ejemplo de la oficina: lunes a jueves 8:30–17:30 y viernes 8:30–15:00
  const plantillaOficina = () => setForm({
    ...form,
    dias: [0, 1, 2, 3].map((dia) => ({ dia, hora_entrada: '08:30', hora_salida: '17:30' })).concat({ dia: 4, hora_entrada: '08:30', hora_salida: '15:00' }),
  })

  const setEsp = (i, k, conv = (v) => v) => (e) => setForm({
    ...form, especiales: form.especiales.map((x, j) => (j === i ? { ...x, [k]: conv(e.target.type === 'checkbox' ? e.target.checked : e.target.value) } : x)),
  })
  const toggleDiaEsp = (i, d) => setForm({
    ...form,
    especiales: form.especiales.map((x, j) => (j === i ? { ...x, dias: x.dias.includes(d) ? x.dias.filter((y) => y !== d) : [...x.dias, d].sort() } : x)),
  })

  return (
    <>
    <SedeActual que="Los turnos nuevos y la rotación" />
    <div className="card">
      <div className="fila" style={{ marginBottom: 14 }}>
        <div className="muted">Define los horarios. Se usan para prellenar permisos y limitar su duración a la jornada de ese día.</div>
        <div className="espacio" />
        <button className="btn btn-primary" onClick={() => setForm(VACIO)}><Plus size={16} /> Nuevo turno</button>
      </div>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Turno</th><th>Horario</th><th>Jornada</th><th>Horarios especiales</th><th>Estado</th><th /></tr></thead>
          <tbody>
            {lista.map((t) => (
              <tr key={t.id}>
                <td><b>{t.nombre}</b>{t.sede_nombre && <div className="muted" style={{ fontSize: 11 }}>{t.sede_nombre}</div>}
                  {t.descripcion && <div className="muted" style={{ fontSize: 11 }}>{t.descripcion}</div>}</td>
                <td>{t.resumen || `${hhmm(t.hora_entrada)}–${hhmm(t.hora_salida)}`}
                  {t.dias?.length > 0 && <div className="muted" style={{ fontSize: 11 }}>General: {hhmm(t.hora_entrada)}–{hhmm(t.hora_salida)}</div>}</td>
                <td>{t.horas_jornada} h</td>
                <td>
                  {(t.especiales || []).map((e) => (
                    <div key={e.id} className="turno-esp" style={{ opacity: e.activo ? 1 : 0.5 }}>
                      <CalendarClock size={12} /> <b>{e.nombre}</b> {e.dias.map((d) => DIAS_CORTOS[d]).join('')} {hhmm(e.hora_entrada)}–{hhmm(e.hora_salida)}
                      <span className="muted"> · {cadaTxt(e.cada_semanas)} · desde {fmtFecha(e.fecha_inicio, false)}{e.fecha_fin ? ` al ${fmtFecha(e.fecha_fin, false)}` : ''}</span>
                    </div>
                  ))}
                </td>
                <td>{t.activo ? 'Activo' : 'Inactivo'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="icon-btn" onClick={() => abrir(t)}><Pencil size={16} /></button>{' '}
                  <button className="icon-btn rojo" onClick={() => borrar(t)}><Trash2 size={16} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {form && (
        <Modal titulo={form.id ? 'Editar turno' : 'Nuevo turno'} onClose={() => setForm(null)} ancho
          pie={<><button className="btn" onClick={() => setForm(null)}>Cancelar</button><button className="btn btn-primary" onClick={guardar}>Guardar</button></>}>
          <div className="form-grid">
            <label className="campo full">Nombre<input value={form.nombre} onChange={set('nombre')} /></label>
            <label className="campo">Entrada (horario general)<input type="time" value={form.hora_entrada} onChange={set('hora_entrada')} /></label>
            <label className="campo">Salida (horario general)<input type="time" value={form.hora_salida} onChange={set('hora_salida')} /></label>
            <label className="campo">Horas por jornada<input type="number" min={1} max={24} value={form.horas_jornada} onChange={set('horas_jornada')} /></label>
            <label className="checkbox" style={{ alignSelf: 'end' }}><input type="checkbox" checked={form.activo} onChange={set('activo')} /> Activo</label>
            <label className="campo full">Descripción<input value={form.descripcion || ''} onChange={set('descripcion')} /></label>
          </div>

          <div className="turno-sec">
            <div className="fila">
              <b>Horario por día</b>
              <span className="muted" style={{ fontSize: 12 }}>Los días sin horario propio usan el general.</span>
              <div className="espacio" />
              <button className="btn btn-sm" onClick={plantillaOficina} title="Lunes a jueves 8:30–17:30 y viernes 8:30–15:00">Oficina L–J / V corto</button>
              {form.dias.length > 0 && <button className="btn btn-sm" onClick={() => setForm({ ...form, dias: [] })}>Todos con el general</button>}
            </div>
            <div className="turno-dias">
              {DIAS.map((nombre, i) => {
                const d = delDia(i)
                return (
                  <div key={i} className={`turno-dia ${d ? 'propio' : ''}`}>
                    <label className="checkbox"><input type="checkbox" checked={!!d} onChange={() => togglePropio(i)} /> {nombre}</label>
                    {d ? (
                      <span className="fila" style={{ gap: 6 }}>
                        <input type="time" value={d.hora_entrada} onChange={setDia(i, 'hora_entrada')} aria-label={`Entrada ${nombre}`} />
                        <span>a</span>
                        <input type="time" value={d.hora_salida} onChange={setDia(i, 'hora_salida')} aria-label={`Salida ${nombre}`} />
                      </span>
                    ) : <span className="muted">{i < 5 ? `General · ${form.hora_entrada} a ${form.hora_salida}` : 'General / descanso'}</span>}
                  </div>
                )
              })}
            </div>
          </div>

          <div className="turno-sec">
            <div className="fila">
              <b><CalendarClock size={15} style={{ verticalAlign: -2 }} /> Horarios especiales</b>
              <span className="muted" style={{ fontSize: 12 }}>Reemplazan el horario en ciertas semanas (p. ej. Short Friday).</span>
              <div className="espacio" />
              <button className="btn btn-sm" onClick={() => setForm({ ...form, especiales: [...form.especiales, especialNuevo(form)] })}><Plus size={14} /> Agregar</button>
            </div>
            {form.especiales.length === 0 && <div className="muted" style={{ fontSize: 13, padding: '6px 0' }}>Sin horarios especiales.</div>}
            {form.especiales.map((e, i) => (
              <div key={i} className="turno-especial">
                <div className="te-grid">
                  <label className="campo">Nombre<input value={e.nombre} onChange={setEsp(i, 'nombre')} /></label>
                  <label className="campo">Desde<input type="date" value={e.fecha_inicio} onChange={setEsp(i, 'fecha_inicio')} /></label>
                  <label className="campo">Hasta (opcional)<input type="date" value={e.fecha_fin} min={e.fecha_inicio} onChange={setEsp(i, 'fecha_fin')} /></label>
                  <label className="campo">Se repite
                    <select value={e.cada_semanas} onChange={setEsp(i, 'cada_semanas', Number)}>
                      {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{cadaTxt(n)}</option>)}
                    </select>
                  </label>
                  <label className="campo">Entrada<input type="time" value={e.hora_entrada} onChange={setEsp(i, 'hora_entrada')} /></label>
                  <label className="campo">Salida<input type="time" value={e.hora_salida} onChange={setEsp(i, 'hora_salida')} /></label>
                </div>
                <div className="fila" style={{ gap: 4, marginTop: 6 }}>
                  <span className="muted" style={{ fontSize: 12 }}>Días:</span>
                  {DIAS_CORTOS.map((c, d) => (
                    <button key={d} type="button" title={DIAS[d]} className={`dia-chip ${e.dias.includes(d) ? 'on' : ''}`} onClick={() => toggleDiaEsp(i, d)}>{c}</button>
                  ))}
                  <div className="espacio" />
                  <label className="checkbox"><input type="checkbox" checked={e.activo} onChange={setEsp(i, 'activo')} /> Activo</label>
                  <button className="icon-btn rojo" title="Quitar" onClick={() => setForm({ ...form, especiales: form.especiales.filter((_, j) => j !== i) })}><X size={14} /></button>
                </div>
                {e.cada_semanas > 1 && (
                  <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                    Aplica la semana del {fmtFecha(e.fecha_inicio, false)} y luego {cadaTxt(e.cada_semanas)}.
                  </div>
                )}
              </div>
            ))}
          </div>
          {error && <div className="alerta error">{error}</div>}
        </Modal>
      )}
    </div>
    <RotacionTurnos onCambio={cargar} />
    </>
  )
}
