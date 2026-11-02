import { FileText } from 'lucide-react'
import { fmtFecha } from '../utils'

const TIPOS = { laptop: 'Laptop', escritorio: 'De escritorio' }

/** Clase visual de la situación de una salida de equipo. */
export const claseSituacion = (s) => (s.estado === 'rechazado' ? 'rechazado' : s.estado === 'cancelado' ? 'cancelado'
  : s.regreso_registrado || s.estado === 'validado' ? 'validado' : s.estado === 'borrador' ? 'borrador' : 'solicitado')

/** Tabla de salidas de equipo de cómputo; `acciones(s)` pinta los botones de cada fila. */
export default function TablaSalidas({ lista, acciones, conEmpleado = true, vacio = 'Sin solicitudes.', onFormato }) {
  return (
    <div className="tabla-wrap">
      <table className="tabla">
        <thead>
          <tr>{conEmpleado && <th>Empleado</th>}<th>Equipo</th><th>Plazo</th><th>Justificación</th><th>Situación</th><th /></tr>
        </thead>
        <tbody>
          {lista.length === 0 && <tr><td colSpan={6} className="muted" style={{ textAlign: 'center', padding: 20 }}>{vacio}</td></tr>}
          {lista.map((s) => (
            <tr key={s.id}>
              {conEmpleado && (
                <td>{s.usuario_nombre}<div className="muted" style={{ fontSize: 12 }}>No. {s.usuario_numero}{s.usuario_departamento ? ` · ${s.usuario_departamento}` : ''}</div></td>
              )}
              <td>
                <b>{TIPOS[s.tipo_equipo] || s.tipo_equipo}</b> {s.marca} {s.modelo}
                <div className="muted" style={{ fontSize: 12 }}>SN {s.serie}{s.accesorios ? ` · ${s.accesorios}` : ''}</div>
              </td>
              <td style={{ whiteSpace: 'nowrap' }}>{fmtFecha(s.fecha_inicio)} → {fmtFecha(s.fecha_fin)}</td>
              <td className="muted" style={{ maxWidth: 260 }}>{s.justificacion}</td>
              <td>
                <span className={`pill ${claseSituacion(s)}`}>{s.situacion}</span>
                <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                  {s.estado === 'solicitado' && `Autoriza: ${s.aprobador_nombre || 'GH'}`}
                  {s.estado === 'validado' && s.revisado_por_nombre && `Jefe: ${s.revisado_por_nombre}`}
                  {s.ti_estado === 'autorizado' && ` · TI: ${s.ti_por_nombre}`}
                </div>
                {s.motivo_rechazo && <div style={{ fontSize: 11, color: 'var(--danger)' }}>{s.motivo_rechazo}</div>}
              </td>
              <td style={{ whiteSpace: 'nowrap' }}>
                <button className="icon-btn" title="Ver formato F-630-03" onClick={() => onFormato(s)}><FileText size={16} /></button>{' '}
                {acciones && acciones(s)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
