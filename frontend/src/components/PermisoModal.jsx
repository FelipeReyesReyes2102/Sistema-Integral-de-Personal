import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { esAdmin, TIPOS_NOMINA, TIPOS_PERMISO_SOLICITABLES, fmtFecha, hhmm, horasEntre, hoyISO, num } from '../utils'
import FormularioOtek, { Campo } from './FormularioOtek'
import SelectorJefe from './SelectorJefe'

const HORARIO = {
  llegada_tarde: ['Hora de entrada del turno', 'Hora de llegada'],
  salida_temprana: ['Hora de salida', 'Hora de salida del turno'],
  salida_intermedia: ['Sale a las', 'Regresa a las'],
  consulta_medica: ['Sale a consulta', 'Regresa a las'],
}

// Título de la ventana según el tipo de permiso elegido
const TITULOS = {
  llegada_tarde: 'PERMISO DE LLEGADA TARDE',
  salida_temprana: 'PERMISO DE SALIDA TEMPRANA',
  salida_intermedia: 'PERMISO DE SALIDA DURANTE LA JORNADA',
  consulta_medica: 'CONSULTA CON MÉDICO DE PLANTA',
  home_office: 'SOLICITUD DE HOME OFFICE',
}

/** Permisos de salida o ingreso (formato O-tek): llegada tarde, salida temprana, salida intermedia y consulta médica. */
export default function PermisoModal({ tipoInicial = '', fechaInicial, fechaFinInicial, usuario, permiso, onClose, onSaved,
  tiposHabilitados = null }) {
  const [turno, setTurno] = useState(null)
  const [departamentos, setDepartamentos] = useState([])
  const [form, setForm] = useState({
    tipo: permiso?.tipo || tipoInicial,
    fecha: permiso?.fecha || fechaInicial || hoyISO(),
    fecha_fin: permiso?.fecha_fin || fechaFinInicial || fechaInicial || hoyISO(),
    hora_inicio: hhmm(permiso?.hora_inicio) || '',
    hora_fin: hhmm(permiso?.hora_fin) || '',
    motivo: permiso?.motivo || '',
    departamento: permiso?.departamento || usuario?.departamento || '',
    tipo_nomina: permiso?.tipo_nomina || '',
    aprobador_id: permiso?.aprobador_id || null,
  })
  const [firma, setFirma] = useState(null)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const { user } = useAuth()

  useEffect(() => {
    api('/departamentos').then(setDepartamentos).catch(() => {})
  }, [usuario?.id])

  // Horario del turno en la fecha del permiso (horario por día y horarios especiales como Short Friday)
  useEffect(() => {
    if (!form.fecha) return
    api('/turnos/horario', { query: { fecha: form.fecha, ...(usuario?.id ? { usuario_id: usuario.id } : {}) } })
      .then((h) => setTurno(h.turno ? { hora_entrada: h.entrada, hora_salida: h.salida, especial: h.especial } : null))
      .catch(() => setTurno(null))
  }, [usuario?.id, form.fecha])

  // Prellenar con el horario del turno según el tipo
  useEffect(() => {
    if (!turno || permiso) return
    if (form.tipo === 'llegada_tarde') setForm((f) => ({ ...f, hora_inicio: hhmm(turno.hora_entrada), hora_fin: '' }))
    if (form.tipo === 'salida_temprana') setForm((f) => ({ ...f, hora_inicio: '', hora_fin: hhmm(turno.hora_salida) }))
  }, [form.tipo, turno])

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const horas = horasEntre(form.hora_inicio, form.hora_fin)
  const requiereJefe = !esAdmin(usuario)
  const esHO = form.tipo === 'home_office'
  const completo = form.tipo && form.fecha && form.motivo.trim() && form.departamento && (!requiereJefe || form.aprobador_id)
    && (esHO ? form.fecha_fin >= form.fecha : form.hora_inicio && form.hora_fin && form.tipo_nomina)
  const naturales = esHO && form.fecha && form.fecha_fin ? Math.round((new Date(form.fecha_fin) - new Date(form.fecha)) / 864e5) + 1 : 0

  async function guardar(enviar) {
    setError('')
    setGuardando(true)
    const body = {
      ...form, enviar, usuario_id: usuario?.id, firma,
      tipo_nomina: esHO ? null : form.tipo_nomina || null,
      fecha_fin: esHO ? form.fecha_fin : null,
      hora_inicio: esHO ? null : form.hora_inicio || null,
      hora_fin: esHO ? null : form.hora_fin || null,
    }
    try {
      if (permiso) await api(`/permisos/${permiso.id}`, { method: 'PUT', body })
      else await api('/permisos', { method: 'POST', body })
      window.dispatchEvent(new Event('pendientes:refrescar'))
      onSaved()
    } catch (e) {
      setError(e.message)
    } finally {
      setGuardando(false)
    }
  }

  const etiquetas = HORARIO[form.tipo] || ['Hora inicio', 'Hora fin']
  const deptos = form.departamento && !departamentos.includes(form.departamento)
    ? [form.departamento, ...departamentos] : departamentos

  const paraOtro = usuario && user && usuario.id !== user.id
  const titulo = TITULOS[form.tipo] || 'PERMISO DE SALIDA O INGRESO'

  return (
    <FormularioOtek titulo={titulo.charAt(0) + titulo.slice(1).toLowerCase()} subtitulo={paraOtro ? `Para: ${usuario.nombre}` : null}
      onClose={onClose} onFirma={setFirma} enviando={guardando}
      enviarDeshabilitado={!completo || !firma} onEnviar={() => guardar(true)}
      pieExtra={
        <button className="btn btn-sm" disabled={!form.tipo || (!esHO && (!form.hora_inicio || !form.hora_fin)) || guardando}
          onClick={() => guardar(false)}>Guardar borrador</button>
      }>
      <Campo label="Tipo de permiso" requerido full>
        <select value={form.tipo} onChange={set('tipo')}>
          <option value="">Selecciona…</option>
          {Object.entries(TIPOS_PERMISO_SOLICITABLES)
            .filter(([k]) => !tiposHabilitados || tiposHabilitados.includes(k) || k === permiso?.tipo)
            .map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Campo>

      <Campo label={esHO ? 'Desde' : 'Fecha'} requerido>
        <input type="date" value={form.fecha} onChange={(e) => setForm({ ...form, fecha: e.target.value, fecha_fin: form.fecha_fin < e.target.value ? e.target.value : form.fecha_fin })} />
      </Campo>
      {esHO ? (
        <Campo label="Hasta" requerido ayuda={naturales > 0 ? `${naturales} día(s) naturales; solo cuentan tus días laborales.` : null}>
          <input type="date" value={form.fecha_fin} min={form.fecha} onChange={set('fecha_fin')} />
        </Campo>
      ) : (
        <Campo label="Horario" requerido
          ayuda={turno ? `Horario ese día: ${hhmm(turno.hora_entrada)} - ${hhmm(turno.hora_salida)}${turno.especial ? ` (${turno.especial})` : ''}` : null}>
          <div className="fo-horas">
            <input type="time" value={form.hora_inicio} onChange={set('hora_inicio')} title={etiquetas[0]} aria-label={etiquetas[0]} />
            <span>a</span>
            <input type="time" value={form.hora_fin} onChange={set('hora_fin')} title={etiquetas[1]} aria-label={etiquetas[1]} />
            <b>{form.hora_inicio && form.hora_fin ? `${num(horas)} h` : ''}</b>
          </div>
        </Campo>
      )}

      <Campo label="Departamento" requerido full={esHO}>
        <select value={form.departamento} onChange={set('departamento')}>
          <option value="">Selecciona…</option>
          {deptos.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </Campo>
      {!esHO && (
        <Campo label="Tiempo en nómina" requerido>
          <select value={form.tipo_nomina} onChange={set('tipo_nomina')}>
            <option value="">Selecciona…</option>
            {Object.entries(TIPOS_NOMINA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Campo>
      )}

      <Campo label={esHO ? 'Actividades a realizar' : 'Motivo'} requerido full>
        <input value={form.motivo} onChange={set('motivo')} />
      </Campo>
      <Campo label="Jefe que aprueba" requerido={requiereJefe} full>
        <SelectorJefe empleado={usuario} value={form.aprobador_id}
          onChange={(v) => setForm((f) => ({ ...f, aprobador_id: v }))} />
      </Campo>

      <div className="full fo-mensajes">
        {esHO && <div className="fo-ayuda">El home office no descuenta vacaciones ni horas; requiere la aprobación de tu jefe.</div>}
        {form.tipo && !esHO && <div className="fo-ayuda">{etiquetas[0]} → {etiquetas[1]}.</div>}
        {error && <div className="alerta error">{error}</div>}
        {completo && !firma && <div className="fo-ayuda">Firma en el recuadro de la derecha para enviar.</div>}
      </div>
    </FormularioOtek>
  )
}
