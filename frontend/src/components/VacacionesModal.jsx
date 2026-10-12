import { useEffect, useState } from 'react'
import { api } from '../api'
import { esAdmin, fmtFecha, num } from '../utils'
import FormularioOtek, { Campo } from './FormularioOtek'
import SelectorJefe from './SelectorJefe'

/** Solicitud de vacaciones (formato O-tek) con cálculo en vivo de días y saldo. */
export default function VacacionesModal({ periodos, usuarioId, empleado, solicitud, inicial, onClose, onSaved }) {
  const vigentes = periodos.filter((p) => p.vigente || p.id === solicitud?.periodo_id)
  const [form, setForm] = useState({
    // Por defecto el periodo vigente más antiguo con saldo, para no perder días al cumplir 18 meses
    periodo_id: solicitud?.periodo_id || [...vigentes].reverse().find((p) => p.horas_disponible > 0)?.id || vigentes[0]?.id || '',
    fecha_inicio: solicitud?.fecha_inicio || inicial?.fecha_inicio || '',
    fecha_fin: solicitud?.fecha_fin || inicial?.fecha_fin || '',
    comentario: solicitud?.comentario || '',
    aprobador_id: solicitud?.aprobador_id || null,
  })
  const [firma, setFirma] = useState(null)
  const [calc, setCalc] = useState(null)
  const [dias, setDias] = useState(null) // días laborales del rango (no depende del periodo)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const requiereJefe = !esAdmin(empleado)

  // Días a disfrutar: se calculan en cuanto hay fechas, excluyendo fines de semana/descansos y festivos
  useEffect(() => {
    setDias(null)
    if (!form.fecha_inicio || !form.fecha_fin) return
    if (form.fecha_fin < form.fecha_inicio) {
      setDias({ error: 'La fecha final no puede ser anterior a la inicial.' })
      return
    }
    const t = setTimeout(() => {
      api('/vacaciones/dias-laborales', {
        method: 'POST', body: { fecha_inicio: form.fecha_inicio, fecha_fin: form.fecha_fin, usuario_id: usuarioId },
      }).then(setDias).catch((e) => setDias({ error: e.message }))
    }, 200)
    return () => clearTimeout(t)
  }, [form.fecha_inicio, form.fecha_fin])

  useEffect(() => {
    setCalc(null)
    if (!form.periodo_id || !form.fecha_inicio || !form.fecha_fin) return
    const t = setTimeout(() => {
      api('/vacaciones/calcular', {
        method: 'POST',
        body: {
          periodo_id: Number(form.periodo_id), fecha_inicio: form.fecha_inicio, fecha_fin: form.fecha_fin,
          usuario_id: usuarioId, excluir_id: solicitud?.id,
        },
      }).then((c) => { setCalc(c); setError('') }).catch((e) => setError(e.message))
    }, 250)
    return () => clearTimeout(t)
  }, [form.periodo_id, form.fecha_inicio, form.fecha_fin])

  async function guardar(enviar) {
    setError('')
    setGuardando(true)
    const body = { ...form, periodo_id: Number(form.periodo_id), enviar, usuario_id: usuarioId, firma }
    try {
      if (solicitud) await api(`/vacaciones/${solicitud.id}`, { method: 'PUT', body })
      else await api('/vacaciones', { method: 'POST', body })
      window.dispatchEvent(new Event('pendientes:refrescar'))
      onSaved()
    } catch (e) {
      setError(e.message)
    } finally {
      setGuardando(false)
    }
  }

  const periodo = periodos.find((p) => p.id === Number(form.periodo_id))
  const hd = periodo?.horas_por_dia || dias?.horas_por_dia || 8
  const nDias = calc?.dias_habiles ?? dias?.dias_habiles
  const nHoras = calc?.horas ?? dias?.horas
  const excluidos = dias?.excluidos || []
  const resumenExcluidos = excluidos.length
    ? `No se cuentan: ${excluidos.map((e) => `${fmtFecha(e.fecha)} (${e.motivo.replace('Festivo: ', '')})`).join(', ')}.`
    : 'Todos los días del rango son laborales.'
  const restante = calc ? (calc.horas_disponible - calc.horas) / hd : null
  const datosValidos = calc && calc.errores.length === 0 && (!requiereJefe || form.aprobador_id)

  return (
    <FormularioOtek titulo="SOLICITUD DE VACACIONES" onClose={onClose} onFirma={setFirma} enviando={guardando}
      enviarDeshabilitado={!datosValidos || !firma} onEnviar={() => guardar(true)}
      pieExtra={
        <button className="btn btn-sm" disabled={!datosValidos || guardando} onClick={() => guardar(false)}>Guardar borrador</button>
      }>
      {vigentes.length === 0 && (
        <div className="alerta warn full">
          Aún no tienes periodos de vacaciones disponibles: se generan al cumplir cada año de servicio
          {empleado?.fecha_ingreso ? ` (fecha de ingreso ${fmtFecha(empleado.fecha_ingreso, false)})` : ''}.
        </div>
      )}

      <Campo label="Nombre de Solicitante" requerido>
        <input value={empleado?.nombre || ''} readOnly />
      </Campo>
      <Campo label="Fecha Ingreso" requerido>
        <input value={empleado?.fecha_ingreso ? fmtFecha(empleado.fecha_ingreso, false) : ''} readOnly />
      </Campo>

      <Campo label="Periodo al que corresponden los días a tomar"
        ayuda={periodo ? `Vence el ${fmtFecha(periodo.fecha_vencimiento, false)}; después de 18 meses los días no usados se pierden.` : null}>
        <select value={form.periodo_id} onChange={set('periodo_id')}>
          {vigentes.map((p) => (
            <option key={p.id} value={p.id}>{p.nombre} (año {p.numero} · vence {fmtFecha(p.fecha_vencimiento, false)})</option>
          ))}
        </select>
      </Campo>
      <Campo label="Días totales generados en el periodo">
        <input value={periodo ? `${num(periodo.dias_total)} días${hd === 12 ? ' (de 12 h)' : ''}` : ''} readOnly />
      </Campo>

      <Campo label="Desde (primer día de vacaciones)" requerido>
        <input type="date" value={form.fecha_inicio} onChange={set('fecha_inicio')} />
      </Campo>
      <Campo label="Hasta (último día de vacaciones)" requerido>
        <input type="date" value={form.fecha_fin} min={form.fecha_inicio} onChange={set('fecha_fin')} />
      </Campo>

      <Campo label="Número de días a disfrutar"
        ayuda={dias?.error || (nDias !== undefined
          ? resumenExcluidos
          : 'Se calcula automáticamente con las fechas: no cuentan fines de semana, descansos ni festivos.')}>
        <input value={nDias !== undefined ? `${nDias} día${nDias === 1 ? '' : 's'} laborable${nDias === 1 ? '' : 's'} (${num(nHoras)} h)` : ''}
          readOnly placeholder="Elige las fechas" />
      </Campo>
      <Campo label="Saldo de días del periodo indicado"
        ayuda={calc && restante !== null ? `Después de esta solicitud te quedarán ${num(restante)} días.` : null}>
        <input value={calc ? `${num(calc.dias_disponible)} días` : periodo ? `${num(periodo.dias_disponible)} días` : ''} readOnly />
      </Campo>

      <Campo label="Correo Jefe Directo" requerido={requiereJefe}>
        <SelectorJefe empleado={empleado} value={form.aprobador_id}
          onChange={(v) => setForm((f) => ({ ...f, aprobador_id: v }))} />
      </Campo>
      <Campo label="Comentario (opcional)">
        <input value={form.comentario} onChange={set('comentario')} />
      </Campo>

      <div className="full">
        {periodo && (
          <div className="fo-ayuda" style={{ marginBottom: 6 }}>
            {periodo.bloque_cumplido
              ? `Ya cumpliste tu bloque de ${periodo.minimo_dias} días seguidos en este periodo.`
              : `Al menos una vez en el periodo debes tomar ${periodo.minimo_dias} días seguidos.`}
          </div>
        )}
        {calc?.errores.map((e) => <div key={e} className="alerta error">{e}</div>)}
        {calc?.advertencias.map((e) => <div key={e} className="alerta warn">{e}</div>)}
        {error && <div className="alerta error">{error}</div>}
        {datosValidos && !firma && <div className="fo-ayuda">Firma en el recuadro inferior para poder enviar la solicitud.</div>}
      </div>
    </FormularioOtek>
  )
}
