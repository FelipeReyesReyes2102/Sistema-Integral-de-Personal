import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../api'
import { ESTADOS_INCAPACIDAD, RESULTADOS_CONSULTA, ROLES, TIPOS_INCAPACIDAD, hhmm, hoyISO } from '../utils'
import Avatar from './Avatar'
import FormularioOtek, { Campo } from './FormularioOtek'

const MED_VACIO = { nombre: '', dosis: '', frecuencia: '', duracion: '' }
const ahoraHHMM = () => new Date().toTimeString().slice(0, 5)

/** Registro (o edición) de una consulta por el médico de planta. */
export default function ConsultaModal({ consulta, onClose, onSaved }) {
  const [tipo, setTipo] = useState(consulta?.paciente_rol || '')
  const [buscar, setBuscar] = useState('')
  const [pacientes, setPacientes] = useState([])
  const [form, setForm] = useState({
    paciente_id: consulta?.paciente_id || '',
    fecha: consulta?.fecha || hoyISO(),
    hora_inicio: hhmm(consulta?.hora_inicio) || ahoraHHMM(),
    hora_fin: hhmm(consulta?.hora_fin) || '',
    sintomas: consulta?.sintomas || '',
    diagnostico: consulta?.diagnostico || '',
    indicaciones: consulta?.indicaciones || '',
    resultado: consulta?.resultado || 'regresa_labores',
  })
  const incPrevia = consulta?.incapacidad || null
  const [conInc, setConInc] = useState(!!incPrevia)
  const [inc, setInc] = useState({
    fecha_inicio: incPrevia?.fecha_inicio || hoyISO(), fecha_fin: incPrevia?.fecha_fin || hoyISO(),
    tipo: incPrevia?.tipo || 'enfermedad_general', folio: incPrevia?.folio || '', observaciones: incPrevia?.observaciones || '',
  })
  const incBloqueada = incPrevia && incPrevia.estado !== 'solicitado'
  const [meds, setMeds] = useState(consulta?.medicamentos?.length ? consulta.medicamentos.map(({ id, ...m }) => m) : [{ ...MED_VACIO }])
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  // Lista de pacientes filtrada por tipo de usuario y búsqueda
  useEffect(() => {
    const t = setTimeout(() => {
      api('/consultas/pacientes', { query: { rol: tipo, q: buscar } }).then((ps) => {
        // conservar al paciente ya elegido aunque no coincida con el filtro
        if (consulta && !ps.some((p) => p.id === consulta.paciente_id)) {
          ps = [{ id: consulta.paciente_id, nombre: consulta.paciente_nombre, numero_empleado: consulta.paciente_numero,
                  rol: consulta.paciente_rol, departamento: consulta.paciente_departamento }, ...ps]
        }
        setPacientes(ps)
      }).catch((e) => setError(e.message))
    }, 200)
    return () => clearTimeout(t)
  }, [tipo, buscar])

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const setMed = (i, k) => (e) => setMeds(meds.map((m, j) => (j === i ? { ...m, [k]: e.target.value } : m)))
  const paciente = pacientes.find((p) => p.id === Number(form.paciente_id))
  const setI = (k) => (e) => setInc({ ...inc, [k]: e.target.value, ...(k === 'fecha_inicio' && inc.fecha_fin < e.target.value ? { fecha_fin: e.target.value } : {}) })
  const diasInc = conInc && inc.fecha_inicio && inc.fecha_fin ? Math.round((new Date(inc.fecha_fin) - new Date(inc.fecha_inicio)) / 864e5) + 1 : 0
  const listo = form.paciente_id && form.fecha && form.hora_inicio && form.sintomas.trim().length >= 3 && (!conInc || diasInc > 0)

  async function guardar() {
    setError('')
    setGuardando(true)
    const body = {
      ...form, paciente_id: Number(form.paciente_id), hora_fin: form.hora_fin || null,
      medicamentos: meds.filter((m) => m.nombre.trim()).map((m) => ({
        nombre: m.nombre.trim(), dosis: m.dosis || null, frecuencia: m.frecuencia || null, duracion: m.duracion || null,
      })),
      incapacidad: conInc ? { ...inc, folio: inc.folio.trim() || null, observaciones: inc.observaciones.trim() || null } : null,
    }
    try {
      if (consulta) await api(`/consultas/${consulta.id}`, { method: 'PUT', body })
      else await api('/consultas', { method: 'POST', body })
      onSaved()
    } catch (e) {
      setError(e.message)
    } finally {
      setGuardando(false)
    }
  }

  return (
    <FormularioOtek titulo="Consulta médica" onClose={onClose} sinFirma textoEnviar="Guardar consulta"
      onEnviar={guardar} enviarDeshabilitado={!listo} enviando={guardando}>
      <Campo label="Tipo de usuario">
        <select value={tipo} onChange={(e) => { setTipo(e.target.value); setForm({ ...form, paciente_id: '' }) }}>
          <option value="">Todos</option>
          {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Campo>
      <Campo label="Buscar empleado">
        <input value={buscar} onChange={(e) => setBuscar(e.target.value)} placeholder="Nombre, número o departamento" />
      </Campo>

      <Campo label="Paciente" requerido full>
        <select value={form.paciente_id} onChange={set('paciente_id')}>
          <option value="">{pacientes.length ? 'Selecciona al empleado…' : 'Sin resultados'}</option>
          {pacientes.map((p) => (
            <option key={p.id} value={p.id}>
              {p.numero_empleado} — {p.nombre} · {ROLES[p.rol]}{p.departamento ? ` · ${p.departamento}` : ''}
            </option>
          ))}
        </select>
      </Campo>
      {paciente && (
        <div className="full persona" style={{ marginTop: -6 }}>
          <Avatar usuario={paciente} tam={36} />
          <span className="muted" style={{ fontSize: 13 }}>
            {paciente.nombre} · No. {paciente.numero_empleado} · {ROLES[paciente.rol]}{paciente.puesto ? ` · ${paciente.puesto}` : ''}
            {paciente.telefono && <><br />Tel. {paciente.telefono}</>}
            {(paciente.contacto_nombre || paciente.contacto_telefono) && (
              <><br />Contacto de emergencia: {[paciente.contacto_nombre, paciente.contacto_telefono].filter(Boolean).join(' · ')}</>
            )}
          </span>
        </div>
      )}

      <Campo label="Fecha de la consulta" requerido>
        <input type="date" value={form.fecha} max={hoyISO()} onChange={set('fecha')} />
      </Campo>
      <Campo label="Horario (llegada a salida)" requerido>
        <div className="fo-horas">
          <input type="time" value={form.hora_inicio} onChange={set('hora_inicio')} aria-label="Hora de llegada" />
          <span>a</span>
          <input type="time" value={form.hora_fin} onChange={set('hora_fin')} aria-label="Hora de salida" />
        </div>
      </Campo>

      <Campo label="Síntomas" requerido full>
        <textarea className="fo-textarea" rows={3} value={form.sintomas} onChange={set('sintomas')}
          placeholder="Ej. dolor de cabeza, mareo, temperatura 38 °C" />
      </Campo>
      <Campo label="Diagnóstico" full>
        <textarea className="fo-textarea" rows={2} value={form.diagnostico} onChange={set('diagnostico')} />
      </Campo>

      <div className="fo-campo full">
        <span className="fo-label">Medicamento recetado</span>
        <div className="meds">
          {meds.map((m, i) => (
            <div key={i} className="med-fila">
              <input value={m.nombre} onChange={setMed(i, 'nombre')} placeholder="Medicamento" aria-label="Medicamento" />
              <input value={m.dosis} onChange={setMed(i, 'dosis')} placeholder="Dosis (500 mg)" aria-label="Dosis" />
              <input value={m.frecuencia} onChange={setMed(i, 'frecuencia')} placeholder="Frecuencia (cada 8 h)" aria-label="Frecuencia" />
              <input value={m.duracion} onChange={setMed(i, 'duracion')} placeholder="Duración (3 días)" aria-label="Duración" />
              <button type="button" className="icon-btn rojo" title="Quitar" onClick={() => setMeds(meds.length > 1 ? meds.filter((_, j) => j !== i) : [{ ...MED_VACIO }])}>
                <Trash2 size={15} />
              </button>
            </div>
          ))}
          <button type="button" className="btn btn-sm" onClick={() => setMeds([...meds, { ...MED_VACIO }])}><Plus size={14} /> Agregar medicamento</button>
        </div>
      </div>

      <Campo label="Indicaciones" full>
        <textarea className="fo-textarea" rows={2} value={form.indicaciones} onChange={set('indicaciones')}
          placeholder="Ej. reposo, hidratación, regresar si persisten los síntomas" />
      </Campo>
      <Campo label="Resultado de la consulta" requerido>
        <select value={form.resultado} onChange={set('resultado')}>
          {Object.entries(RESULTADOS_CONSULTA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Campo>
      <div className="fo-ayuda" style={{ alignSelf: 'end' }}>
        Solo el paciente y el servicio médico verán los síntomas, el diagnóstico y los medicamentos.
      </div>

      <div className="fo-campo full incap-form">
        <label className="checkbox">
          <input type="checkbox" checked={conInc} disabled={!!incBloqueada} onChange={(e) => setConInc(e.target.checked)} />
          <b>Generar incapacidad</b>
          {incPrevia && <span className={`pill ${incPrevia.estado}`} style={{ marginLeft: 8 }}>{ESTADOS_INCAPACIDAD[incPrevia.estado]}</span>}
        </label>
        {conInc && (
          <div className="incap-grid">
            <label>Desde<input type="date" value={inc.fecha_inicio} onChange={setI('fecha_inicio')} disabled={!!incBloqueada} /></label>
            <label>Hasta<input type="date" value={inc.fecha_fin} min={inc.fecha_inicio} onChange={setI('fecha_fin')} disabled={!!incBloqueada} /></label>
            <label>Tipo
              <select value={inc.tipo} onChange={setI('tipo')} disabled={!!incBloqueada}>
                {Object.entries(TIPOS_INCAPACIDAD).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label>Folio (IMSS u otro)<input value={inc.folio} onChange={setI('folio')} maxLength={40} disabled={!!incBloqueada} /></label>
            <label className="incap-obs">Observaciones para el jefe y GH
              <input value={inc.observaciones} onChange={setI('observaciones')} maxLength={500} disabled={!!incBloqueada}
                placeholder="Sin datos clínicos: p. ej. reposo en casa" />
            </label>
            <div className="fo-ayuda incap-obs">
              {diasInc > 0 ? `${diasInc} día(s) naturales. ` : ''}
              {incBloqueada
                ? 'El jefe ya revisó la incapacidad; ya no se puede modificar.'
                : 'Al guardar se envía al jefe del empleado para que la valide; al validarla se notifica a GH. El jefe y GH no ven síntomas, diagnóstico ni medicamentos.'}
            </div>
          </div>
        )}
      </div>
      {error && <div className="full alerta error">{error}</div>}
    </FormularioOtek>
  )
}
