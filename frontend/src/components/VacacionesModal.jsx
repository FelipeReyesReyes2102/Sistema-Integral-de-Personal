import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { esAdmin, fmtFecha, num, parseISO } from '../utils'
import FormularioOtek, { Campo } from './FormularioOtek'
import SelectorJefe from './SelectorJefe'

/** Solicitud de vacaciones (formato O-tek) con cálculo en vivo de días y saldo. */
export default function VacacionesModal({ periodos, usuarioId, empleado, solicitud, inicial, onClose, onSaved }) {
  const vigentes = periodos.filter((p) => p.vigente || p.id === solicitud?.periodo_id)
  const conSaldo = vigentes.filter((p) => p.horas_disponible > 0)
  // Con saldo en varios periodos, por defecto modo General ('') : primero los días del periodo más antiguo
  let periodoInicial
  if (solicitud?.periodo_id) periodoInicial = solicitud.periodo_id
  else if (inicial && inicial.periodo_id !== undefined) periodoInicial = inicial.periodo_id || ''
  else periodoInicial = conSaldo.length > 1 ? '' : conSaldo[conSaldo.length - 1]?.id || vigentes[0]?.id || ''
  const [form, setForm] = useState({
    periodo_id: periodoInicial,
    fecha_inicio: solicitud?.fecha_inicio || inicial?.fecha_inicio || '',
    fecha_fin: solicitud?.fecha_fin || inicial?.fecha_fin || '',
    comentario: solicitud?.comentario || '',
    aprobador_id: solicitud?.aprobador_id || null,
  })
  const [firma, setFirma] = useState(null)
  // Vacaciones por horas (si la jornada del empleado lo permite y es un solo día)
  const [porHoras, setPorHoras] = useState(!!solicitud?.por_horas)
  const [horas, setHoras] = useState(solicitud?.por_horas ? solicitud.horas : 4)
  const [calc, setCalc] = useState(null)
  const [dias, setDias] = useState(null) // días laborales del rango (no depende del periodo)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const unDia = !!form.fecha_inicio && form.fecha_inicio === form.fecha_fin
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
    const general = !form.periodo_id
    if ((general && conSaldo.length === 0) || !form.fecha_inicio || !form.fecha_fin) return
    const t = setTimeout(() => {
      api('/vacaciones/calcular', {
        method: 'POST',
        body: {
          periodo_id: general ? null : Number(form.periodo_id), fecha_inicio: form.fecha_inicio, fecha_fin: form.fecha_fin,
          usuario_id: usuarioId, excluir_id: solicitud?.id, horas: unDia && porHoras ? Number(horas) || null : null,
        },
      }).then((c) => { setCalc(c); setError('') }).catch((e) => setError(e.message))
    }, 250)
    return () => clearTimeout(t)
  }, [form.periodo_id, form.fecha_inicio, form.fecha_fin, porHoras, horas])

  async function guardar(enviar) {
    setError('')
    setGuardando(true)
    const body = { ...form, periodo_id: form.periodo_id ? Number(form.periodo_id) : null, enviar, usuario_id: usuarioId, firma,
      horas: unDia && porHoras ? Number(horas) : null }
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
  const anterior = conSaldo.length > 1 ? conSaldo[conSaldo.length - 1] : null
  const limite = new Date()
  limite.setMonth(limite.getMonth() + 6)
  const porVencer = anterior && parseISO(anterior.fecha_vencimiento) <= limite ? anterior : null
  const mostrarPeriodo = !!porVencer || (conSaldo.length > 1 && (solicitud || inicial?.periodo_id))
  const reparto = calc?.reparto || []
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
            {conSaldo.length > 1 && (
              <option value="">General · {num(conSaldo.reduce((t, p) => t + p.dias_disponible, 0))} día(s) · primero el periodo más antiguo</option>
            )}
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

      {unDia && (calc?.permite_horas || porHoras) && (
        <Campo label="Duración" full ayuda={`Tu jornada es de ${calc?.horas_dia || hd} h; por horas, mínimo ${calc?.minimo_horas || 1} h.`}>
          <div className="fila" style={{ gap: 10 }}>
            <label className="checkbox"><input type="radio" checked={!porHoras} onChange={() => setPorHoras(false)} /> Día completo</label>
            <label className="checkbox"><input type="radio" checked={porHoras} onChange={() => setPorHoras(true)} /> Por horas</label>
            {porHoras && (
              <span className="fila" style={{ gap: 4 }}>
                <input type="number" style={{ width: 80 }} min={calc?.minimo_horas || 1} max={(calc?.horas_dia || hd) - 0.5} step={0.5}
                  value={horas} onChange={(e) => setHoras(e.target.value)} /> h
              </span>
            )}
          </div>
        </Campo>
      )}

      <div className="fo-resumen full">
        {dias?.error ? <span className="texto-error">{dias.error}</span> : nDias !== undefined ? (
          <>
            {unDia && porHoras
              ? <div><b>{num(Number(horas) || 0)} h</b> de vacaciones <span className="muted">({num((Number(horas) || 0) / hd)} d)</span></div>
              : <div><b>{nDias}</b> día{nDias === 1 ? '' : 's'} laborable{nDias === 1 ? '' : 's'} <span className="muted">({num(nHoras)} h)</span></div>}
            {calc && (
              <div className="muted">
                Saldo {num(calc.dias_disponible)} d{restante !== null && <> · te quedarán <b>{num(restante)} d</b></>}
              </div>
            )}
          </>
        ) : <span className="muted">Elige las fechas; no cuentan fines de semana, descansos ni festivos.</span>}
        {reparto.length > 1 && (
          <div className="fo-ayuda" style={{ flexBasis: '100%', color: 'var(--navy)' }}>
            Se descuentan {reparto.map((t) => `${t.dias} d del ${t.periodo_nombre}`).join(' y ')} ({reparto.length} solicitudes enlazadas).
          </div>
        )}
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
