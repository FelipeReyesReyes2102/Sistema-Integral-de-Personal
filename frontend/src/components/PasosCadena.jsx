import { Check, Clock, MinusCircle, X } from 'lucide-react'

const ESTADO = {
  aprobado: { t: 'Aprobó', i: Check, c: 'var(--success, #2e7d32)' },
  rechazado: { t: 'Rechazó', i: X, c: 'var(--danger, #c62828)' },
  pendiente: { t: 'Pendiente', i: Clock, c: 'var(--warning, #a35d00)' },
  en_espera: { t: 'En espera', i: Clock, c: 'var(--muted, #667085)' },
  omitido: { t: 'Omitido (sin aprobador)', i: MinusCircle, c: 'var(--muted, #667085)' },
}

/** Línea de pasos de la cadena de aprobación de un permiso. */
export default function PasosCadena({ pasos }) {
  if (!pasos?.length) return null
  return (
    <ol className="pasos-cadena">
      {pasos.map((p) => {
        const e = ESTADO[p.estado] || ESTADO.en_espera
        const Icono = e.i
        const quien = p.decidido_por_nombre || p.aprobador_nombre
        return (
          <li key={p.orden} className={`paso-${p.estado}`}>
            <Icono size={14} style={{ color: e.c, flex: 'none' }} />
            <span>
              <b>{p.etiqueta}</b>{quien && p.etiqueta !== quien ? ` · ${quien}` : ''}
              <span className="muted"> — {e.t}{p.fecha ? ` el ${p.fecha.slice(0, 16).replace('T', ' ')}` : ''}{p.canal === 'teams' ? ' (Teams)' : ''}</span>
              {p.comentario && <div className="muted" style={{ fontSize: 11 }}>{p.comentario}</div>}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
