import { useEffect, useState } from 'react'
import { Lock, Stethoscope } from 'lucide-react'
import { api } from '../api'
import { RESULTADOS_CONSULTA, fmtFecha, hhmm } from '../utils'
import Modal from './Modal'
import IncapacidadInfo from './IncapacidadInfo'

/**
 * Información que cargó el médico. El paciente (y el médico) ven el detalle completo;
 * el jefe o el administrador solo el resumen (fecha y horario).
 */
export default function DetalleConsulta({ consultaId, resumen, onClose }) {
  const [c, setC] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!consultaId) return
    api(`/consultas/${consultaId}`).then(setC).catch((e) => setError(e.message))
  }, [consultaId])

  const base = c || resumen
  return (
    <Modal titulo="Consulta médica" onClose={onClose} pie={<button className="btn" onClick={onClose}>Cerrar</button>}>
      {error && <div className="alerta error">{error}</div>}
      {base && (
        <div className="consulta-cab">
          <div className="avatar" style={{ background: '#e7f4f1', color: '#00796b', width: 40, height: 40, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Stethoscope size={20} />
          </div>
          <div>
            <div style={{ fontWeight: 600 }}>{fmtFecha(base.fecha)} · {hhmm(base.hora_inicio)}{base.hora_fin ? ` - ${hhmm(base.hora_fin)}` : ''}</div>
            <div className="muted" style={{ fontSize: 13 }}>Atendió: {base.medico_nombre || 'Servicio médico'}</div>
          </div>
        </div>
      )}
      {!consultaId && (
        <div className="alerta warn" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Lock size={16} /> La información clínica solo la pueden ver el paciente y el servicio médico.
        </div>
      )}
      {c && (
        <table className="tabla">
          <tbody>
            <tr><td className="muted" style={{ width: 150 }}>Síntomas</td><td style={{ whiteSpace: 'pre-wrap' }}>{c.sintomas}</td></tr>
            <tr><td className="muted">Diagnóstico</td><td style={{ whiteSpace: 'pre-wrap' }}>{c.diagnostico || '—'}</td></tr>
            <tr>
              <td className="muted">Medicamento recetado</td>
              <td>
                {c.medicamentos.length === 0 ? '—' : (
                  <ul className="lista-meds">
                    {c.medicamentos.map((m) => (
                      <li key={m.id}><b>{m.nombre}</b>{[m.dosis, m.frecuencia, m.duracion].filter(Boolean).map((x) => ` · ${x}`).join('')}</li>
                    ))}
                  </ul>
                )}
              </td>
            </tr>
            <tr><td className="muted">Indicaciones</td><td style={{ whiteSpace: 'pre-wrap' }}>{c.indicaciones || '—'}</td></tr>
            <tr><td className="muted">Resultado</td><td>{RESULTADOS_CONSULTA[c.resultado] || c.resultado}</td></tr>
          </tbody>
        </table>
      )}
      <IncapacidadInfo inc={(c || resumen)?.incapacidad} />
    </Modal>
  )
}
