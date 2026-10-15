import { useEffect, useState } from 'react'
import { Clock, RefreshCw } from 'lucide-react'
import { api } from '../api'
import { fmtFecha } from '../utils'

const horario = (t) => (t ? t.resumen || `${t.hora_entrada} - ${t.hora_salida}` : '')

/** Horario de cada día de esta semana; marca el día de hoy y los horarios especiales (p. ej. Short Friday). */
export function SemanaHorario({ dias }) {
  if (!dias?.length) return null
  const hoy = new Date().toLocaleDateString('en-CA')
  return (
    <div className="semana-horario">
      {dias.filter((d, i) => i < 5 || d.especial).map((d) => (
        <div key={d.fecha} className={`${d.fecha === hoy ? 'hoy' : ''} ${d.especial ? 'especial' : ''}`} title={d.especial || ''}>
          <span>{d.dia}</span>
          <b>{d.entrada}–{d.salida}</b>
          {d.especial && <small>{d.especial}</small>}
        </div>
      ))}
    </div>
  )
}

/** Tarjeta "Mi turno": turno actual, de la próxima semana y siguientes (con rotación). */
export default function MiTurno({ usuarioId, incrustado = false }) {
  const [d, setD] = useState(null)
  useEffect(() => {
    api('/turnos/mi-turno', { query: usuarioId ? { usuario_id: usuarioId } : undefined }).then(setD).catch(() => setD(null))
  }, [usuarioId])

  if (!d || !d.actual) return null
  const sig = d.siguiente_semana?.turno
  const cambia = d.rotacion_activa && sig && sig.id !== d.actual.id

  if (incrustado) {
    return (
      <div className="pf-turno">
        <div><Clock size={13} /> Turno <b>{d.actual.nombre}</b> <span className="muted">
          {d.hoy ? `hoy ${d.hoy.entrada} - ${d.hoy.salida}${d.hoy.especial ? ` (${d.hoy.especial})` : ''}` : horario(d.actual)}</span></div>
        {d.rotacion_activa && sig && (
          <div className={`ps-bloque ${cambia ? '' : 'ok'}`} title={d.semanas.map((s) => `${fmtFecha(s.desde)}: ${s.turno?.nombre || '—'}`).join(' · ')}>
            <RefreshCw size={11} /> Próx. semana: <b>{sig.nombre}</b>{cambia ? ' (cambio)' : ''}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="card mi-turno" style={{ marginBottom: 14 }}>
      <div className="fila" style={{ gap: 8, marginBottom: 8 }}>
        <Clock size={18} color="var(--primary)" />
        <b>{usuarioId ? 'Turno' : 'Mi turno'}</b>
        {d.grupo && <span className="chip">{d.grupo}</span>}
        {d.rotacion_activa && <span className="chip" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}><RefreshCw size={11} /> Rotación activa</span>}
      </div>
      <div className="mt-actual">
        <div>
          <span className="muted">Esta semana</span>
          <div className="mt-turno">{d.actual.nombre}</div>
          <div className="muted">{horario(d.actual)}</div>
          <SemanaHorario dias={d.semana_actual} />
        </div>
        {d.rotacion_activa && sig && (
          <div className={cambia ? 'mt-cambio' : ''}>
            <span className="muted">Próxima semana ({fmtFecha(d.siguiente_semana.desde)})</span>
            <div className="mt-turno">{sig.nombre}</div>
            <div className="muted">{horario(sig)}{cambia ? ' · cambio de turno' : ' · sin cambio'}</div>
          </div>
        )}
      </div>
      {d.rotacion_activa && (
        <div className="mt-semanas">
          {d.semanas.map((s) => (
            <div key={s.desde} title={`${fmtFecha(s.desde)} al ${fmtFecha(s.hasta)}`}>
              <span>{fmtFecha(s.desde).slice(4, 9)}</span>
              <b>{s.turno?.nombre || '—'}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
