import { HeartPulse } from 'lucide-react'
import { ESTADOS_INCAPACIDAD, TIPOS_INCAPACIDAD, fmtFecha } from '../utils'

/** Resumen de una incapacidad (sin información clínica): fechas, días, tipo, folio y quién la valida. */
export default function IncapacidadInfo({ inc }) {
  if (!inc) return null
  return (
    <div className="incap-card">
      <div className="incap-cab">
        <HeartPulse size={16} /> <b>Incapacidad</b>
        <span className={`pill ${inc.estado}`}>{ESTADOS_INCAPACIDAD[inc.estado] || inc.estado}</span>
      </div>
      <div className="incap-fila"><span>Fechas</span><div>{fmtFecha(inc.fecha_inicio)} → {fmtFecha(inc.fecha_fin)} ({inc.dias} día(s))</div></div>
      <div className="incap-fila"><span>Tipo</span><div>{TIPOS_INCAPACIDAD[inc.tipo] || inc.tipo}</div></div>
      {inc.folio && <div className="incap-fila"><span>Folio</span><div>{inc.folio}</div></div>}
      {inc.observaciones && <div className="incap-fila"><span>Observaciones</span><div>{inc.observaciones}</div></div>}
      <div className="incap-fila"><span>{inc.estado === 'solicitado' ? 'Valida' : 'Revisó'}</span>
        <div>{inc.revisado_por_nombre || inc.aprobador_nombre || 'Gestión Humana'}</div></div>
      {inc.motivo_rechazo && <div className="incap-fila"><span>Motivo de rechazo</span><div style={{ color: 'var(--danger)' }}>{inc.motivo_rechazo}</div></div>}
    </div>
  )
}
