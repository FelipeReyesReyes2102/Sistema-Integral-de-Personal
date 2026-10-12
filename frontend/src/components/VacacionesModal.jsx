import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { esAdmin, fmtFecha, num, parseISO } from '../utils'
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
  const { user } = useAuth()

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
  const restante = calc ? (calc.horas_disponible - calc.horas) / hd : null
  const datosValidos = calc && calc.errores.length === 0 && (!requiereJefe || form.aprobador_id)

  // El periodo solo se elige cuando quedan días del periodo anterior y faltan 6 meses o menos para que se pierdan
  const conSaldo = vigentes.filter((p) => p.horas_disponible > 0)
  const anterior = conSaldo.length > 1 ? conSaldo[conSaldo.length - 1] : null
  const limite = new Date()
  limite.setMonth(limite.getMonth() + 6)
  const porVencer = anterior && parseISO(anterior.fecha_vencimiento) <= limite ? anterior : null
  const mostrarPeriodo = !!porVencer || (solicitud && conSaldo.length > 1)
  const paraOtro = empleado && user && empleado.id !== user.id

  return (
    <FormularioOtek titulo="Solicitud de vacaciones" subtitulo={paraOtro ? `Para: ${empleado.nombre}` : null}
      onClose={onClose} onFirma={setFirma} enviando={guardando}
      enviarDeshabilitado={!datosValidos || !firma} onEnviar={() => guardar(true)}
      pieExtra={
        <button className="btn btn-sm" disabled={!datosValidos || guardando} onClick={() => guardar(false)}>Guardar borrador</button>
      }>
      {vigentes.length === 0 && (
        <div className="alerta warn full" style={{ margin: 0 }}>
          Aún no tienes días de vacaciones: se generan al cumplir cada año de servicio.
        </div>
      )}

      {mostrarPeriodo && (
        <Campo label="Periodo" full
          ayuda={porVencer ? `Te quedan ${num(porVencer.dias_disponible)} día(s) del ${porVencer.nombre}; vencen el ${fmtFecha(porVencer.fecha_vencimiento, false)}.` : null}>
          <select value={form.periodo_id} onChange={set('periodo_id')}>
            {vigentes.map((p) => (
              <option key={p.id} value={p.id}>{p.nombre} · {num(p.dias_disponible)} día(s) · vence {fmtFecha(p.fecha_vencimiento, false)}</option>
            ))}
          </select>
        </Campo>
      )}

      <Campo label="Desde" requerido>
        <input type="date" value={form.fecha_inicio} onChange={set('fecha_inicio')} />
      </Campo>
      <Campo label="Hasta" requerido>
        <input type="date" value={form.fecha_fin} min={form.fecha_inicio} onChange={set('fecha_fin')} />
      </Campo>

      <div className="fo-resumen full">
        {dias?.error ? <span className="texto-error">{dias.error}</span> : nDias !== undefined ? (
          <>
            <div><b>{nDias}</b> día{nDias === 1 ? '' : 's'} laborable{nDias === 1 ? '' : 's'} <span className="muted">({num(nHoras)} h)</span></div>
            {calc && (
              <div className="muted">
                Saldo {num(calc.dias_disponible)} d{restante !== null && <> · te quedarán <b>{num(restante)} d</b></>}
              </div>
            )}
          </>
        ) : <span className="muted">Elige las fechas; no cuentan fines de semana, descansos ni festivos.</span>}
        {excluidos.length > 0 && (
          <div className="fo-ayuda" style={{ flexBasis: '100%' }}>
            No se cuentan: {excluidos.map((e) => `${fmtFecha(e.fecha)} (${e.motivo.replace('Festivo: ', '')})`).join(', ')}.
          </div>
        )}
      </div>

      <Campo label="Jefe que aprueba" requerido={requiereJefe} full>
        <SelectorJefe empleado={empleado} value={form.aprobador_id}
          onChange={(v) => setForm((f) => ({ ...f, aprobador_id: v }))} />
      </Campo>
      <Campo label="Comentario (opcional)" full>
        <input value={form.comentario} onChange={set('comentario')} />
      </Campo>

      <div className="full fo-mensajes">
        {periodo && !periodo.bloque_cumplido && (
          <div className="fo-ayuda">Al menos una vez en el periodo debes tomar {periodo.minimo_dias} días seguidos.</div>
        )}
        {calc?.errores.map((e) => <div key={e} className="alerta error">{e}</div>)}
        {calc?.advertencias.map((e) => <div key={e} className="alerta warn">{e}</div>)}
        {error && <div className="alerta error">{error}</div>}
        {datosValidos && !firma && <div className="fo-ayuda">Firma en el recuadro de la derecha para enviar.</div>}
      </div>
    </FormularioOtek>
  )
}
