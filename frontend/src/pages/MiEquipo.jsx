import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Eye } from 'lucide-react'
import { api } from '../api'
import Avatar from '../components/Avatar'
import { ROLES, fmtFecha, num } from '../utils'

/** Personal a cargo del jefe: vacaciones tomadas, solicitadas y restantes del periodo. */
export default function MiEquipo() {
  const navigate = useNavigate()
  const [equipo, setEquipo] = useState(null)
  const [buscar, setBuscar] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { api('/equipo').then(setEquipo).catch((e) => setError(e.message)) }, [])

  const filtrado = useMemo(
    () => (equipo || []).filter((m) => !buscar || m.usuario.nombre.toLowerCase().includes(buscar.toLowerCase())),
    [equipo, buscar],
  )
  const totales = useMemo(() => ({
    personas: equipo?.length || 0,
    hoy: equipo?.filter((m) => m.de_vacaciones_hoy).length || 0,
    pendientes: equipo?.reduce((s, m) => s + m.pendientes_por_aprobar, 0) || 0,
    restantes: equipo?.reduce((s, m) => s + m.dias_restantes, 0) || 0,
    porVencer: equipo?.filter((m) => m.dias_por_vencer > 0).length || 0,
  }), [equipo])

  const pct = (v, t) => `${t > 0 ? Math.max(0, (v / t) * 100) : 0}%`

  return (
    <>
      <div className="card fila" style={{ gap: 40, marginBottom: 16 }}>
        <div className="stat"><b>{totales.personas}</b><span>Personas a cargo</span></div>
        <div className="stat"><b>{totales.hoy}</b><span>De vacaciones hoy</span></div>
        <div className="stat"><b>{totales.pendientes}</b><span>Solicitudes pendientes</span></div>
        <div className="stat"><b>{num(totales.restantes, 1)}</b><span>Días restantes del equipo (periodo actual)</span></div>
        <div className="stat"><b style={{ color: totales.porVencer ? '#8a6400' : undefined }}>{totales.porVencer}</b><span>Con días por vencer (18 meses)</span></div>
      </div>

      <div className="card">
        <div className="fila" style={{ marginBottom: 14 }}>
          <input style={{ maxWidth: 280 }} placeholder="Buscar colaborador…" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
          <div className="espacio" />
          <div className="leyenda-cal" style={{ marginTop: 0 }}>
            <span><i style={{ background: 'var(--blue)' }} /> Tomados</span>
            <span><i style={{ background: 'var(--yellow)' }} /> Solicitados</span>
            <span><i style={{ background: 'var(--green)' }} /> Restantes</span>
          </div>
        </div>
        {error && <div className="alerta error">{error}</div>}
        <div className="tabla-wrap">
          <table className="tabla">
            <thead>
              <tr>
                <th>Colaborador</th><th>Periodo</th><th>Uso del periodo</th><th>Otorgados</th><th>Tomados</th>
                <th>Solicitados</th><th>Restantes</th><th>Vence</th><th>Próximas vacaciones</th><th>Pendientes</th><th />
              </tr>
            </thead>
            <tbody>
              {equipo && filtrado.length === 0 && (
                <tr><td colSpan={11} className="muted" style={{ textAlign: 'center', padding: 24 }}>
                  No tienes personal a cargo. El administrador asigna el jefe de cada empleado en Empleados.
                </td></tr>
              )}
              {filtrado.map((m) => (
                <tr key={m.usuario.id}>
                  <td>
                    <div className="persona">
                      <Avatar usuario={m.usuario} tam={34} />
                      <div>
                        <div style={{ fontWeight: 500 }}>{m.usuario.nombre}</div>
                        <div className="muted" style={{ fontSize: 12 }}>
                          {m.usuario.puesto || ROLES[m.usuario.rol]}{m.usuario.grupo_nombre && ` · ${m.usuario.grupo_nombre}`}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td>{m.periodo_actual || '—'}</td>
                  <td>
                    <div className="mini-barra" title={`${num(m.dias_tomados)} tomados / ${num(m.dias_solicitados)} solicitados / ${num(m.dias_restantes)} restantes`}>
                      <div style={{ width: pct(m.dias_tomados, m.dias_total), background: 'var(--blue)' }} />
                      <div style={{ width: pct(m.dias_solicitados, m.dias_total), background: 'var(--yellow)' }} />
                      <div style={{ width: pct(m.dias_restantes, m.dias_total), background: 'var(--green)' }} />
                    </div>
                  </td>
                  <td>{num(m.dias_total)} d</td>
                  <td>{num(m.dias_tomados)} d</td>
                  <td>{num(m.dias_solicitados)} d</td>
                  <td>
                    <b>{num(m.dias_restantes)} d</b>
                    {m.dias_restantes_vigentes > m.dias_restantes && (
                      <div className="muted" style={{ fontSize: 11 }}>{num(m.dias_restantes_vigentes)} d en todos los periodos</div>
                    )}
                    {m.dias_por_vencer > 0 && (
                      <div style={{ fontSize: 11, color: '#8a6400' }}>
                        ⚠ {num(m.dias_por_vencer)} d vencen el {fmtFecha(m.fecha_por_vencer, false)}
                      </div>
                    )}
                    {m.dias_perdidos > 0 && (
                      <div style={{ fontSize: 11, color: 'var(--danger)' }}>{num(m.dias_perdidos)} d perdidos</div>
                    )}
                  </td>
                  <td>{m.vence ? fmtFecha(m.vence, false) : '—'}</td>
                  <td>
                    {m.de_vacaciones_hoy ? <span className="pill validado">De vacaciones</span>
                      : m.proximas_vacaciones ? fmtFecha(m.proximas_vacaciones) : '—'}
                  </td>
                  <td>{m.pendientes_por_aprobar > 0 ? <span className="pill solicitado">{m.pendientes_por_aprobar}</span> : '—'}</td>
                  <td>
                    <button className="icon-btn" title="Ver vacaciones y permisos"
                      onClick={() => navigate(`/mi-equipo/${m.usuario.id}/vacaciones`)}><Eye size={16} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
