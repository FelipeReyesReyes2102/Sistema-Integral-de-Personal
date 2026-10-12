import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../api'
import { num } from '../utils'
import ConfigMicrosoft from '../components/ConfigMicrosoft'
import ConfigCorreo from '../components/ConfigCorreo'
import { useAuth } from '../auth'
import { esSuperAdmin } from '../utils'

export default function Configuracion() {
  const [reglas, setReglas] = useState([])
  const [msg, setMsg] = useState(null)
  const { user } = useAuth()
  useEffect(() => { api('/reglas-antiguedad').then(setReglas) }, [])

  const set = (i, k) => (e) => setReglas(reglas.map((r, j) => (j === i ? { ...r, [k]: e.target.value } : r)))

  function agregar() {
    const ult = reglas[reglas.length - 1]
    const desde = ult ? Number(ult.anios_hasta) + 1 : 1
    setReglas([...reglas, { anios_desde: desde, anios_hasta: desde + 4, dias: ult ? Number(ult.dias) + 2 : 12 }])
  }

  async function guardar() {
    setMsg(null)
    try {
      const body = reglas.map((r) => ({ anios_desde: Number(r.anios_desde), anios_hasta: Number(r.anios_hasta), dias: Number(r.dias) }))
      setReglas(await api('/reglas-antiguedad', { method: 'PUT', body }))
      setMsg({ ok: true, t: 'Tabla guardada. Los saldos se recalculan automáticamente al consultarlos.' })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  return (
    <>
    <div className="vac-layout">
      <div className="card">
        <h3 style={{ marginBottom: 6 }}>Días de vacaciones por antigüedad</h3>
        <p className="muted" style={{ marginTop: 0 }}>Días de 8 horas que corresponden a cada año de servicio.</p>
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
          <button className="btn" onClick={agregar}><Plus size={16} /> Agregar rango</button>
          <div className="espacio" />
          <button className="btn btn-primary" onClick={guardar}>Guardar tabla</button>
        </div>
        {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
      </div>
      <div className="card">
        <h3 style={{ marginBottom: 10 }}>Reglas vigentes</h3>
        <ul style={{ lineHeight: 1.7, paddingLeft: 18, margin: 0 }}>
          <li><b>Oficinas y administradores:</b> 1 día = 8 h. Año 1 = 12 días.</li>
          <li><b>Planta:</b> se otorgan las mismas horas (días × 8 h) y cada día de planta consume 12 h. Año 1 = 12 × 8 = 96 h ÷ 12 = <b>8 días</b>.</li>
          <li>Los días laborales de planta se calculan con el ciclo del grupo asignado (p. ej. 4×4). Los días de descanso y festivos no se descuentan.</li>
          <li><b>Bloque obligatorio:</b> en cada periodo se deben tomar al menos una vez <b>6 días seguidos</b> (oficinas) o <b>4</b> (planta).
            Se permiten solicitudes más cortas, pero mientras no se haya solicitado ese bloque no se pueden pedir días sueltos que dejen
            el saldo por debajo de él. Ej.: con 8 días y sin bloque, 3 días no se permiten (quedarían 5); 2 sí.</li>
          <li>Estados: Borrador → Solicitado → Validado / Rechazado. Borrador y Solicitado ya apartan saldo.</li>
          <li>Permisos (llegada tarde, salida temprana, salida intermedia y consulta con el médico de planta) se registran en horas y no descuentan vacaciones.</li>
        </ul>
      </div>
    </div>
    <ConfigCorreo />
    {esSuperAdmin(user) && <ConfigMicrosoft />}
    </>
  )
}
