import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../api'
import { num } from '../utils'
import ConfigCorreo from '../components/ConfigCorreo'
import ConfigPolitica from '../components/ConfigPolitica'
import ConfigTiposPermiso from '../components/ConfigTiposPermiso'
import { useAuth } from '../auth'
import { esAdmin } from '../utils'
import SedeActual from '../components/SedeActual'

export default function Configuracion() {
  const [reglas, setReglas] = useState([])
  const [tabla, setTabla] = useState(null) // {sede_nombre, propia, principal}
  const [msg, setMsg] = useState(null)
  const { user } = useAuth()
  const aplicar = (t) => { setTabla(t); setReglas(t.reglas) }
  useEffect(() => { api('/reglas-antiguedad').then(aplicar) }, [])
  const puedeEditar = esAdmin(user)

  const set = (i, k) => (e) => setReglas(reglas.map((r, j) => (j === i ? { ...r, [k]: e.target.value } : r)))

  function agregar() {
    const ult = reglas[reglas.length - 1]
    const desde = ult ? Number(ult.anios_hasta) + 1 : 1
    setReglas([...reglas, { anios_desde: desde, anios_hasta: desde + 4, dias: ult ? Number(ult.dias) + 2 : 12 }])
  }

  async function usarPrincipal() {
    if (!window.confirm(`¿Quitar la tabla propia de ${tabla.sede_nombre} y usar la de ${tabla.principal}?`)) return
    try {
      aplicar(await api('/reglas-antiguedad', { method: 'DELETE' }))
      setMsg({ ok: true, t: `${tabla.sede_nombre} ahora usa la tabla de ${tabla.principal}.` })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  async function guardar() {
    setMsg(null)
    try {
      const body = reglas.map((r) => ({ anios_desde: Number(r.anios_desde), anios_hasta: Number(r.anios_hasta), dias: Number(r.dias) }))
      aplicar(await api('/reglas-antiguedad', { method: 'PUT', body }))
      setMsg({ ok: true, t: `Tabla de ${tabla?.sede_nombre} guardada. Los saldos de sus empleados se recalculan automáticamente.` })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  return (
    <>
    <div className="vac-layout">
      <div className="card">
        <h3 style={{ marginBottom: 6 }}>Días de vacaciones por antigüedad{tabla?.sede_nombre ? ` · ${tabla.sede_nombre}` : ''}</h3>
        <p className="muted" style={{ marginTop: 0 }}>Días de 8 horas que corresponden a cada año de servicio en esta sede.</p>
        <SedeActual que="Los cambios de la tabla" />
        {tabla && !tabla.propia && (
          <div className="alerta warn" style={{ marginTop: 0 }}>
            Esta sede aún no tiene tabla propia: usa la de <b>{tabla.principal}</b>. Al guardar se crea su tabla.
          </div>
        )}
        <div className="tabla-wrap">
          <table className="tabla">
            <thead><tr><th>Años desde</th><th>Años hasta</th><th>Días (oficinas)</th><th>Días planta (12 h)</th><th /></tr></thead>
            <tbody>
              {reglas.map((r, i) => (
                <tr key={i}>
                  <td><input type="number" min={1} value={r.anios_desde} onChange={set(i, 'anios_desde')} /></td>
                  <td><input type="number" min={1} value={r.anios_hasta} onChange={set(i, 'anios_hasta')} /></td>
                  <td><input type="number" min={1} value={r.dias} onChange={set(i, 'dias')} /></td>
                  <td className="muted">{num((Number(r.dias) * 8) / 12)} d</td>
                  <td><button className="icon-btn rojo" onClick={() => setReglas(reglas.filter((_, j) => j !== i))}><Trash2 size={15} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="fila" style={{ marginTop: 12 }}>
          {puedeEditar && <>
            <button className="btn" onClick={agregar}><Plus size={16} /> Agregar rango</button>
            {tabla?.propia && tabla.sede_nombre !== tabla.principal && (
              <button className="btn btn-sm" onClick={usarPrincipal}>Usar la tabla de {tabla.principal}</button>
            )}
            <div className="espacio" />
            <button className="btn btn-primary" onClick={guardar}>Guardar tabla</button>
          </>}
        </div>
        {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
      </div>
      <ConfigPolitica />
    </div>
    <ConfigTiposPermiso />
    <ConfigCorreo />
    </>
  )
}
