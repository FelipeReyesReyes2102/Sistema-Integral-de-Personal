import { useEffect, useState } from 'react'
import { Layers, Pencil, Plus, Trash2, UserCheck, Users } from 'lucide-react'
import { api } from '../api'
import Modal from '../components/Modal'
import SedeActual from '../components/SedeActual'
import { useAuth } from '../auth'
import { DIAS_SEMANA, fmtFecha, hoyISO } from '../utils'

const VACIO = {
  nombre: '', descripcion: '', tipo_ciclo: 'rotativo', dias_semana: '0,1,2,3,4', dias_trabajo: 4, dias_descanso: 4,
  fecha_inicio_ciclo: hoyISO(), color: '#1976d2', activo: true,
}

function describirCiclo(g) {
  if (g.tipo_ciclo === 'rotativo') {
    return `${g.dias_trabajo}x${g.dias_descanso} (trabaja ${g.dias_trabajo}, descansa ${g.dias_descanso}) desde ${fmtFecha(g.fecha_inicio_ciclo, false)}`
  }
  const dias = g.dias_semana.split(',').filter(Boolean).map((d) => DIAS_SEMANA[Number(d)])
  return `Semanal: ${dias.join(', ')}`
}

export default function Grupos() {
  const { user } = useAuth()
  const variasSedes = (user?.sedes || []).length > 1
  const [lista, setLista] = useState([])
  const [form, setForm] = useState(null)
  const [miembros, setMiembros] = useState(null)
  const [jefes, setJefes] = useState(null) // {titulo, ruta, sede_id, actuales, nota} de los jefes que se editan
  const [area, setArea] = useState(null) // {grupo, area} cuyos integrantes se editan
  const [error, setError] = useState('')
  const cargar = () => api('/grupos').then(setLista)
  useEffect(() => { cargar() }, [])

  async function guardar() {
    setError('')
    const body = {
      ...form, dias_trabajo: Number(form.dias_trabajo), dias_descanso: Number(form.dias_descanso),
      fecha_inicio_ciclo: form.fecha_inicio_ciclo || null,
    }
    try {
      if (form.id) await api(`/grupos/${form.id}`, { method: 'PUT', body })
      else await api('/grupos', { method: 'POST', body })
      setForm(null)
      cargar()
    } catch (e) {
      setError(e.message)
    }
  }

  async function nuevaArea(g) {
    const nombre = window.prompt(`Nombre del área en ${g.nombre} (p. ej. Calidad, AMP, APT):`)
    if (!nombre?.trim()) return
    await api(`/grupos/${g.id}/subgrupos`, { method: 'POST', body: { nombre: nombre.trim() } }).then(cargar).catch((e) => alert(e.message))
  }
  async function renombrarArea(a) {
    const nombre = window.prompt('Nuevo nombre del área:', a.nombre)
    if (!nombre?.trim() || nombre.trim() === a.nombre) return
    await api(`/subgrupos/${a.id}`, { method: 'PUT', body: { nombre: nombre.trim() } }).then(cargar).catch((e) => alert(e.message))
  }
  async function borrarArea(a) {
    if (!window.confirm(`¿Eliminar el área ${a.nombre}? Sus ${a.total_miembros} integrante(s) siguen en el grupo, a cargo de los jefes del grupo.`)) return
    await api(`/subgrupos/${a.id}`, { method: 'DELETE' }).then(cargar).catch((e) => alert(e.message))
  }
  const jefesDeGrupo = (g) => setJefes({
    titulo: `Jefes de ${g.nombre}`, ruta: `/grupos/${g.id}/jefes`, sede_id: g.sede_id, actuales: g.jefes,
    nota: g.subgrupos.length ? 'Atienden a los integrantes que no están en ninguna área.' : 'Atienden a todos los integrantes del grupo.',
  })
  const jefesDeArea = (g, a) => setJefes({
    titulo: `Jefes de ${g.nombre} · ${a.nombre}`, ruta: `/subgrupos/${a.id}/jefes`, sede_id: g.sede_id, actuales: a.jefes,
    nota: `Atienden solo a los integrantes del área ${a.nombre}.`,
  })

  async function borrar(g) {
    if (!window.confirm(`¿Eliminar ${g.nombre}? Sus ${g.total_miembros} miembro(s) quedarán sin grupo.`)) return
    await api(`/grupos/${g.id}`, { method: 'DELETE' }).catch((e) => alert(e.message))
    cargar()
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const diasSel = new Set((form?.dias_semana || '').split(',').filter(Boolean))
  const toggleDia = (i) => {
    const s = new Set(diasSel)
    s.has(String(i)) ? s.delete(String(i)) : s.add(String(i))
    setForm({ ...form, dias_semana: [...s].sort().join(',') })
  }

  return (
    <>
      <SedeActual que="Los grupos nuevos" />
      <div className="fila" style={{ marginBottom: 14 }}>
        <div className="muted">Los grupos definen qué días trabaja el personal de planta; con ellos se cuentan los días de vacaciones.</div>
        <div className="espacio" />
        <button className="btn btn-primary" onClick={() => setForm(VACIO)}><Plus size={16} /> Nuevo grupo</button>
      </div>
      <div className="grupos">
        {lista.map((g) => (
          <div key={g.id} className="card grupo-card" style={{ borderTopColor: g.color, opacity: g.activo ? 1 : 0.6 }}>
            <div className="fila">
              <h3 style={{ fontSize: 17 }}>{g.nombre}</h3>
              {variasSedes && <div className="muted" style={{ fontSize: 12 }}>{g.sede_nombre}</div>}
              <div className="espacio" />
              <button className="icon-btn" onClick={() => setForm({ ...g, fecha_inicio_ciclo: g.fecha_inicio_ciclo || '' })}><Pencil size={15} /></button>
              <button className="icon-btn rojo" onClick={() => borrar(g)}><Trash2 size={15} /></button>
            </div>
            <div className="muted" style={{ margin: '8px 0' }}>{g.descripcion}</div>
            <div style={{ fontSize: 13 }}>{describirCiclo(g)}</div>
            <div className="grupo-jefes" title="Cualquiera de ellos ve a los integrantes en Mi equipo y aprueba sus solicitudes">
              <UserCheck size={14} /> {g.jefes.length ? g.jefes.map((j) => j.nombre).join(', ') : <span className="muted">Sin jefes asignados</span>}
            </div>
            <div className="fila" style={{ marginTop: 10 }}>
              <span className="chip"><Users size={12} /> {g.total_miembros} empleado(s)</span>
              <div className="espacio" />
              <button className="btn btn-sm" onClick={() => jefesDeGrupo(g)}>Jefes</button>
              <button className="btn btn-sm" onClick={() => setMiembros(g)}>Asignar empleados</button>
            </div>
            <div className="grupo-areas">
              <div className="fila" style={{ gap: 6 }}>
                <Layers size={14} /> <b>Áreas</b>
                <span className="muted" style={{ fontSize: 12 }}>cada una con sus jefes</span>
                <div className="espacio" />
                <button className="btn btn-sm" onClick={() => nuevaArea(g)}><Plus size={13} /> Área</button>
              </div>
              {g.subgrupos.map((a) => (
                <div key={a.id} className="grupo-area">
                  <div className="ga-datos">
                    <b>{a.nombre}</b> <span className="muted">· {a.total_miembros} integrante(s)</span>
                    <div className="muted" style={{ fontSize: 12 }}>
                      Jefes: {a.jefes.length ? a.jefes.map((j) => j.nombre).join(', ') : <span style={{ color: 'var(--danger)' }}>sin asignar</span>}
                    </div>
                  </div>
                  <button className="btn btn-sm" onClick={() => jefesDeArea(g, a)}>Jefes</button>
                  <button className="btn btn-sm" onClick={() => setArea({ grupo: g, area: a })}>Integrantes</button>
                  <button className="icon-btn" title="Renombrar" onClick={() => renombrarArea(a)}><Pencil size={14} /></button>
                  <button className="icon-btn rojo" title="Eliminar área" onClick={() => borrarArea(a)}><Trash2 size={14} /></button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {form && (
        <Modal titulo={form.id ? 'Editar grupo' : 'Nuevo grupo'} onClose={() => setForm(null)}
          pie={<><button className="btn" onClick={() => setForm(null)}>Cancelar</button><button className="btn btn-primary" onClick={guardar}>Guardar</button></>}>
          <div className="form-grid">
            <label className="campo">Nombre<input value={form.nombre} onChange={set('nombre')} /></label>
            <label className="campo">Color<input type="color" value={form.color} onChange={set('color')} style={{ height: 36, padding: 2 }} /></label>
            <label className="campo full">Descripción<input value={form.descripcion || ''} onChange={set('descripcion')} /></label>
            <label className="campo full">Tipo de ciclo
              <select value={form.tipo_ciclo} onChange={set('tipo_ciclo')}>
                <option value="rotativo">Rotativo (N días de trabajo x M de descanso)</option>
                <option value="semanal">Semanal (días fijos)</option>
              </select>
            </label>
            {form.tipo_ciclo === 'rotativo' ? (
              <>
                <label className="campo">Días de trabajo<input type="number" min={1} value={form.dias_trabajo} onChange={set('dias_trabajo')} /></label>
                <label className="campo">Días de descanso<input type="number" min={0} value={form.dias_descanso} onChange={set('dias_descanso')} /></label>
                <label className="campo full">Primer día de trabajo del ciclo
                  <input type="date" value={form.fecha_inicio_ciclo} onChange={set('fecha_inicio_ciclo')} />
                </label>
              </>
            ) : (
              <div className="full fila">
                {DIAS_SEMANA.map((d, i) => (
                  <label key={d} className="checkbox"><input type="checkbox" checked={diasSel.has(String(i))} onChange={() => toggleDia(i)} /> {d}</label>
                ))}
              </div>
            )}
            <label className="checkbox"><input type="checkbox" checked={form.activo} onChange={set('activo')} /> Activo</label>
            {error && <div className="full alerta error">{error}</div>}
          </div>
        </Modal>
      )}
      {miembros && <Miembros grupo={miembros} onClose={() => setMiembros(null)} onSaved={() => { setMiembros(null); cargar() }} />}
      {jefes && <JefesGrupo {...jefes} onClose={() => setJefes(null)} onSaved={() => { setJefes(null); cargar() }} />}
      {area && <IntegrantesArea {...area} onClose={() => setArea(null)} onSaved={() => { setArea(null); cargar() }} />}
    </>
  )
}

function Miembros({ grupo, onClose, onSaved }) {
  const [empleados, setEmpleados] = useState([])
  const [turnos, setTurnos] = useState([])
  const [sel, setSel] = useState(new Set())
  const [turnoId, setTurnoId] = useState('')
  const [buscar, setBuscar] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api('/usuarios', { query: { rol: 'planta', activos: true } }).then((us) => {
      const deSede = us.filter((u) => u.sede_id === grupo.sede_id)
      setEmpleados(deSede)
      setSel(new Set(deSede.filter((u) => u.grupo_id === grupo.id).map((u) => u.id)))
    })
    api('/turnos').then((ts) => setTurnos(ts.filter((t) => t.sede_id === grupo.sede_id)))
  }, [grupo.id])

  const toggle = (id) => {
    const s = new Set(sel)
    s.has(id) ? s.delete(id) : s.add(id)
    setSel(s)
  }

  async function guardar() {
    try {
      await api(`/grupos/${grupo.id}/miembros`, {
        method: 'PUT', body: { usuario_ids: [...sel], turno_id: turnoId ? Number(turnoId) : null },
      })
      onSaved()
    } catch (e) {
      setError(e.message)
    }
  }

  const visibles = empleados.filter((u) => !buscar || u.nombre.toLowerCase().includes(buscar.toLowerCase()))

  return (
    <Modal ancho titulo={`Empleados de ${grupo.nombre}`} onClose={onClose}
      pie={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn btn-primary" onClick={guardar}>Guardar ({sel.size})</button></>}>
      <div className="fila" style={{ marginBottom: 10 }}>
        <input style={{ maxWidth: 260 }} placeholder="Buscar…" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
        <label className="campo" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          Asignar turno a los seleccionados:
          <select style={{ width: 170 }} value={turnoId} onChange={(e) => setTurnoId(e.target.value)}>
            <option value="">No cambiar</option>
            {turnos.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
          </select>
        </label>
      </div>
      <div className="tabla-wrap" style={{ maxHeight: 380, overflowY: 'auto' }}>
        <table className="tabla">
          <thead><tr><th /><th>No.</th><th>Nombre</th><th>Grupo actual</th><th>Turno</th></tr></thead>
          <tbody>
            {visibles.map((u) => (
              <tr key={u.id} onClick={() => toggle(u.id)} style={{ cursor: 'pointer' }}>
                <td><input type="checkbox" checked={sel.has(u.id)} readOnly style={{ width: 'auto' }} /></td>
                <td>{u.numero_empleado}</td>
                <td>{u.nombre}</td>
                <td className="muted">{u.grupo_nombre || '—'}</td>
                <td className="muted">{u.turno_nombre || '—'}</td>
              </tr>
            ))}
            {visibles.length === 0 && <tr><td colSpan={5} className="muted">No hay empleados de planta activos.</td></tr>}
          </tbody>
        </table>
      </div>
      {error && <div className="alerta error">{error}</div>}
    </Modal>
  )
}

/** Jefes de un grupo o de un área: cualquiera de ellos ve a sus integrantes en Mi equipo y aprueba sus solicitudes. */
function JefesGrupo({ titulo, ruta, sede_id: sedeId, actuales, nota, onClose, onSaved }) {
  const [jefes, setJefes] = useState([])
  const [sel, setSel] = useState(() => new Set(actuales.map((j) => j.id)))
  const [buscar, setBuscar] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { api('/jefes', { query: { sede_id: sedeId } }).then(setJefes).catch((e) => setError(e.message)) }, [ruta])

  const toggle = (id) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  async function guardar() {
    try {
      await api(ruta, { method: 'PUT', body: { usuario_ids: [...sel] } })
      onSaved()
    } catch (e) {
      setError(e.message)
    }
  }
  const visibles = jefes.filter((j) => !buscar || j.nombre.toLowerCase().includes(buscar.toLowerCase()))

  return (
    <Modal titulo={titulo} onClose={onClose}
      pie={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn btn-primary" onClick={guardar}>Guardar ({sel.size})</button></>}>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        {nota} Cualquiera de los jefes que marques los ve en <b>Mi equipo</b> y puede aprobar sus solicitudes. Solo aparecen
        personas marcadas como <b>jefe</b> en la sede.
      </p>
      <input placeholder="Buscar jefe…" value={buscar} onChange={(e) => setBuscar(e.target.value)} style={{ marginBottom: 8 }} />
      <div className="tabla-wrap" style={{ maxHeight: 340, overflowY: 'auto' }}>
        <table className="tabla">
          <tbody>
            {visibles.map((j) => (
              <tr key={j.id} onClick={() => toggle(j.id)} style={{ cursor: 'pointer' }}>
                <td style={{ width: 30 }}><input type="checkbox" checked={sel.has(j.id)} readOnly style={{ width: 'auto' }} /></td>
                <td>{j.nombre}<div className="muted" style={{ fontSize: 12 }}>{j.email}</div></td>
              </tr>
            ))}
            {visibles.length === 0 && <tr><td className="muted">No hay jefes en la sede. Marca «Es jefe» en la ficha del empleado.</td></tr>}
          </tbody>
        </table>
      </div>
      {error && <div className="alerta error">{error}</div>}
    </Modal>
  )
}

/** Integrantes de un área: se eligen entre los integrantes del grupo. */
function IntegrantesArea({ grupo, area, onClose, onSaved }) {
  const [empleados, setEmpleados] = useState([])
  const [sel, setSel] = useState(new Set())
  const [buscar, setBuscar] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api('/usuarios', { query: { rol: 'planta', activos: true } }).then((us) => {
      const delGrupo = us.filter((u) => u.grupo_id === grupo.id)
      setEmpleados(delGrupo)
      setSel(new Set(delGrupo.filter((u) => u.subgrupo_id === area.id).map((u) => u.id)))
    }).catch((e) => setError(e.message))
  }, [area.id])

  const toggle = (id) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  async function guardar() {
    try {
      await api(`/subgrupos/${area.id}/miembros`, { method: 'PUT', body: { usuario_ids: [...sel] } })
      onSaved()
    } catch (e) {
      setError(e.message)
    }
  }
  const visibles = empleados.filter((u) => !buscar || u.nombre.toLowerCase().includes(buscar.toLowerCase()))

  return (
    <Modal ancho titulo={`Integrantes de ${grupo.nombre} · ${area.nombre}`} onClose={onClose}
      pie={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn btn-primary" onClick={guardar}>Guardar ({sel.size})</button></>}>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Marca a quienes pertenecen al área: los atenderán los jefes del área. Si alguien estaba en otra área del grupo, se cambia a esta.
        Para que aparezca aquí, primero agrégalo al grupo con <b>Asignar empleados</b>.
      </p>
      <input placeholder="Buscar…" value={buscar} onChange={(e) => setBuscar(e.target.value)} style={{ maxWidth: 260, marginBottom: 8 }} />
      <div className="tabla-wrap" style={{ maxHeight: 380, overflowY: 'auto' }}>
        <table className="tabla">
          <thead><tr><th /><th>No.</th><th>Nombre</th><th>Área actual</th></tr></thead>
          <tbody>
            {visibles.map((u) => (
              <tr key={u.id} onClick={() => toggle(u.id)} style={{ cursor: 'pointer' }}>
                <td><input type="checkbox" checked={sel.has(u.id)} readOnly style={{ width: 'auto' }} /></td>
                <td>{u.numero_empleado}</td>
                <td>{u.nombre}</td>
                <td className="muted">{u.subgrupo_nombre || '—'}</td>
              </tr>
            ))}
            {visibles.length === 0 && <tr><td colSpan={4} className="muted">El grupo no tiene integrantes.</td></tr>}
          </tbody>
        </table>
      </div>
      {error && <div className="alerta error">{error}</div>}
    </Modal>
  )
}
