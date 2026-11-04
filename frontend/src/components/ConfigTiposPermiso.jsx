import { useEffect, useState } from 'react'
import { ListChecks, Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { textoLimite } from '../utils'

const NUEVO = {
  nombre: '', modalidad: 'horas', pide_nomina: true, limite_cantidad: '', limite_unidad: 'dias', limite_periodo: '',
  max_dias_solicitud: '', color: '#6d4c41', activo: true, flujo_id: '',
}
const PERIODOS = { '': 'Sin límite de periodo (en total)', mes: 'Por mes', anio: 'Por año' }

/** Tipos de permiso de la sede: los 4 base (se activan o desactivan) y los que agregue GH, con su límite. */
export default function ConfigTiposPermiso() {
  const [tipos, setTipos] = useState(null)
  const [edicion, setEdicion] = useState(null)
  const [msg, setMsg] = useState(null)
  const [flujos, setFlujos] = useState([])

  const cargar = () => api('/tipos-permiso').then(setTipos).catch((e) => setMsg({ ok: false, t: e.message }))
  useEffect(() => { cargar(); api('/flujos').then(setFlujos).catch(() => {}) }, [])
  if (!tipos) return <div className="card" style={{ marginTop: 24 }}>{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>

  const setE = (k) => (e) => setEdicion({ ...edicion, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const conLimite = edicion && edicion.limite_cantidad !== '' && edicion.limite_cantidad !== null

  const aviso = (t) => {
    setMsg(t)
    cargar()
    window.dispatchEvent(new Event('politica:refrescar'))
  }

  async function guardar() {
    setMsg(null)
    const e = edicion
    const body = {
      nombre: e.nombre.trim(), modalidad: e.modalidad, pide_nomina: e.modalidad === 'horas' && e.pide_nomina, color: e.color,
      activo: e.activo,
      limite_cantidad: conLimite ? Number(e.limite_cantidad) : null,
      limite_unidad: e.modalidad === 'dias' ? 'dias' : e.limite_unidad,
      limite_periodo: e.limite_periodo || null,
      max_dias_solicitud: e.modalidad === 'dias' && e.max_dias_solicitud ? Number(e.max_dias_solicitud) : null,
      flujo_id: e.flujo_id ? Number(e.flujo_id) : null,
    }
    try {
      if (e.id) await api(`/tipos-permiso/${e.id}`, { method: 'PUT', body })
      else await api('/tipos-permiso', { method: 'POST', body })
      setEdicion(null)
      aviso({ ok: true, t: `Tipo de permiso "${body.nombre}" guardado.` })
    } catch (err) {
      setMsg({ ok: false, t: err.message })
    }
  }

  async function borrar(t) {
    if (!window.confirm(`¿Eliminar el tipo de permiso "${t.nombre}"?`)) return
    setMsg(null)
    try {
      await api(`/tipos-permiso/${t.id}`, { method: 'DELETE' })
      aviso({ ok: true, t: `Tipo "${t.nombre}" eliminado.` })
    } catch (err) {
      setMsg({ ok: false, t: err.message })
    }
  }

  const editar = (t) => setEdicion({
    ...t, limite_cantidad: t.limite_cantidad ?? '', limite_periodo: t.limite_periodo || '', max_dias_solicitud: t.max_dias_solicitud ?? '',
    flujo_id: t.flujo_id ?? '',
  })

  return (
    <div className="card" style={{ marginTop: 24 }}>
      <h3 className="fila" style={{ gap: 8, marginBottom: 6 }}><ListChecks size={18} /> Tipos de permiso</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Agrega los permisos que usa la sede y define cuántos días (u horas) se permiten <b>por mes</b>, <b>por año</b> o
        en total. Los tipos base no se eliminan: desactívalos si la sede no los usa. Un tipo con solicitudes registradas solo
        se puede desactivar.
      </p>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Permiso</th><th>Se pide por</th><th>Tiempo en nómina</th><th>Límite</th><th>Máx. por solicitud</th><th>Aprobación</th><th>Estado</th><th /></tr></thead>
          <tbody>
            {tipos.map((t) => (
              <tr key={t.id} className={edicion?.id === t.id ? 'tp-editando' : ''} style={{ opacity: t.activo ? 1 : 0.5 }}>
                <td>
                  <span className="reg-icono" style={{ background: t.color, width: 10, height: 10, marginRight: 6, display: 'inline-block', borderRadius: 3 }} />
                  <b>{t.nombre}</b>{t.base && <span className="muted"> (base)</span>}
                  {t.en_uso > 0 && <div className="muted" style={{ fontSize: 11 }}>{t.en_uso} solicitud(es)</div>}
                </td>
                <td>{t.modalidad === 'dias' ? 'Días (rango de fechas)' : 'Horas (un día, con horario)'}</td>
                <td>{t.modalidad === 'horas' && t.pide_nomina ? 'Lo indica el empleado' : <span className="muted">No aplica</span>}</td>
                <td>{textoLimite(t)}</td>
                <td>{t.modalidad === 'dias' ? `${t.max_dias_solicitud || 31} día(s)` : <span className="muted">—</span>}</td>
                <td>{t.flujo_nombre || <span className="muted">Como la sede</span>}</td>
                <td>{t.activo ? 'Activo' : 'Inactivo'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="icon-btn" title="Editar" disabled={!!edicion} onClick={() => editar(t)}><Pencil size={14} /></button>{' '}
                  {!t.base && <button className="icon-btn rojo" title="Eliminar" disabled={!!edicion} onClick={() => borrar(t)}><Trash2 size={14} /></button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!edicion && <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => setEdicion({ ...NUEVO })}><Plus size={14} /> Agregar tipo de permiso</button>}
      {edicion && <FormularioTipo edicion={edicion} setE={setE} conLimite={conLimite} flujos={flujos}
        onGuardar={guardar} onCancelar={() => setEdicion(null)} />}
      <p className="muted" style={{ fontSize: 12, margin: '8px 0 0' }}>
        En permisos por horas, el límite cuenta <b>permisos</b> (cada solicitud es uno) u <b>horas</b>. En permisos por días cuenta los
        días laborales. Se toman en cuenta los borradores, las solicitudes pendientes y las validadas.
      </p>
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
    </div>
  )
}

/** Formulario para crear o editar un tipo de permiso, con cada dato explicado y un resumen de cómo quedará. */
function FormularioTipo({ edicion: e, setE, conLimite, flujos, onGuardar, onCancelar }) {
  const porDias = e.modalidad === 'dias'
  const flujo = flujos.find((f) => String(f.id) === String(e.flujo_id))
  const limite = textoLimite({ ...e, limite_cantidad: conLimite ? Number(e.limite_cantidad) : null,
    limite_unidad: porDias ? 'dias' : e.limite_unidad })
  return (
    <div className="tp-form">
      <div className="tp-form-cab">
        <h4>{e.id ? <>Editar «{e.nombre}»</> : 'Nuevo tipo de permiso'}</h4>
        {e.base && <span className="muted" style={{ fontSize: 12 }}>Tipo base: el nombre y la forma de pedirse no cambian.</span>}
      </div>

      <div className="tp-seccion">
        <h5>1. Datos generales</h5>
        <div className="pol-grid">
          <label className="campo">Nombre del permiso
            <span className="tp-nombre">
              <input type="color" value={e.color} onChange={setE('color')} title="Color en el calendario" className="tp-color" />
              <input value={e.nombre} onChange={setE('nombre')} placeholder="Ej. Día de cumpleaños" disabled={e.base} autoFocus={!e.id} />
            </span>
            <span className="muted" style={{ fontSize: 11 }}>El color identifica el permiso en el calendario.</span>
          </label>
          <div className="campo">
            <span>Estado</span>
            <label className="checkbox"><input type="checkbox" checked={e.activo} onChange={setE('activo')} /> Activo: los empleados lo pueden solicitar</label>
          </div>
        </div>
      </div>

      <div className="tp-seccion">
        <h5>2. Cómo se solicita</h5>
        <div className="tp-opciones">
          {[['horas', 'Por horas', 'Un solo día, con hora de inicio y de fin (p. ej. salida temprana).'],
            ['dias', 'Por días', 'Un rango de fechas completo (p. ej. home office, día de cumpleaños).']].map(([k, t, d]) => (
            <label key={k} className={`tp-opcion ${e.modalidad === k ? 'activa' : ''} ${e.base ? 'bloqueada' : ''}`}>
              <input type="radio" name="modalidad" value={k} checked={e.modalidad === k} onChange={setE('modalidad')} disabled={e.base} />
              <span><b>{t}</b><span className="muted">{d}</span></span>
            </label>
          ))}
        </div>
        <div className="pol-grid" style={{ marginTop: 10 }}>
          {porDias ? (
            <label className="campo">Máximo de días por solicitud
              <input type="number" min={1} max={365} value={e.max_dias_solicitud} onChange={setE('max_dias_solicitud')} placeholder="31" />
              <span className="muted" style={{ fontSize: 11 }}>Días naturales que puede abarcar una sola solicitud (vacío = 31).</span>
            </label>
          ) : (
            <div className="campo">
              <span>Tiempo en nómina</span>
              <label className="checkbox"><input type="checkbox" checked={e.pide_nomina} onChange={setE('pide_nomina')} /> Pedir al empleado si es con goce, sin goce o reposición</label>
            </div>
          )}
        </div>
      </div>

      <div className="tp-seccion">
        <h5>3. Límite de uso</h5>
        <div className="tp-limite">
          <label className="campo">Cantidad
            <input type="number" min={0.5} step={0.5} value={e.limite_cantidad} onChange={setE('limite_cantidad')} placeholder="Sin límite" />
          </label>
          <label className="campo">Unidad
            {porDias ? <input value="día(s) laborales" disabled /> : (
              <select value={e.limite_unidad} onChange={setE('limite_unidad')}>
                <option value="dias">permisos (cada solicitud cuenta uno)</option>
                <option value="horas">horas</option>
              </select>
            )}
          </label>
          <label className="campo">Periodo
            <select value={e.limite_periodo} onChange={setE('limite_periodo')} disabled={!conLimite}>
              {Object.entries(PERIODOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
        <span className="muted" style={{ fontSize: 11 }}>Deja la cantidad vacía si no hay límite.</span>
      </div>

      <div className="tp-seccion">
        <h5>4. Aprobación</h5>
        <div className="pol-grid">
          <label className="campo">Flujo de aprobación
            <select value={e.flujo_id} onChange={setE('flujo_id')}>
              <option value="">Como la sede (jefe, o jefe y después GH)</option>
              {flujos.map((f) => <option key={f.id} value={f.id}>{f.nombre}{f.activo ? '' : ' (inactivo)'}</option>)}
            </select>
            <span className="muted" style={{ fontSize: 11 }}>
              {flujo ? `Pasos: ${flujo.resumen}` : 'Las cadenas se arman en la pestaña Flujos de aprobación.'}
            </span>
          </label>
        </div>
      </div>

      <div className="tp-resumen">
        <b>Así quedará:</b> {e.nombre.trim() || 'Sin nombre'} · {porDias ? `por días (máx. ${e.max_dias_solicitud || 31} por solicitud)` : 'por horas'}
        {' '}· límite: {limite.toLowerCase()} · aprobación: {flujo ? flujo.nombre : 'como la sede'}{e.activo ? '' : ' · inactivo'}
      </div>

      <div className="fila" style={{ gap: 8, marginTop: 12 }}>
        <div className="espacio" />
        <button className="btn btn-sm" onClick={onCancelar}><X size={14} /> Cancelar</button>
        <button className="btn btn-primary btn-sm" onClick={onGuardar} disabled={e.nombre.trim().length < 2}>
          <Save size={14} /> {e.id ? 'Guardar cambios' : 'Crear tipo de permiso'}
        </button>
      </div>
    </div>
  )
}
