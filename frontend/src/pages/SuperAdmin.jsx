import { useEffect, useState } from 'react'
import { MapPin, ShieldCheck } from 'lucide-react'
import { api, sedeActiva } from '../api'
import ConfigAprobacionFlujo from '../components/ConfigAprobacionFlujo'
import ConfigMicrosoft from '../components/ConfigMicrosoft'
import ConfigSedes from '../components/ConfigSedes'
import ConfigSharePoint from '../components/ConfigSharePoint'

/** Configuración que solo puede cambiar el super administrador: global y las integraciones de cada sede. */
export default function SuperAdmin() {
  const [sedes, setSedes] = useState([])
  const [sedeId, setSedeId] = useState('')
  useEffect(() => {
    api('/sedes').then((l) => {
      setSedes(l)
      const activa = sedeActiva()
      setSedeId(String(l.some((s) => String(s.id) === activa) ? activa : l[0]?.id || ''))
    }).catch(() => {})
  }, [])

  return (
    <>
      <div className="alerta warn" style={{ marginTop: 0, display: 'flex', gap: 8, alignItems: 'center' }}>
        <ShieldCheck size={16} /> Solo un super administrador puede cambiar esta configuración. La de cada sede que maneja
        su GH (política, tabla de antigüedad, correo y caseta) está en Configuración.
      </div>
      <ConfigSedes />
      <ConfigMicrosoft />

      <div className="card sa-sede">
        <h3 className="fila" style={{ gap: 8, margin: 0 }}><MapPin size={18} /> Integraciones por sede</h3>
        <p className="muted" style={{ margin: '4px 0 10px', fontSize: 13 }}>
          Cada sede tiene su propia aprobación en Teams y sus listas de SharePoint. Elige la sede que vas a configurar.
        </p>
        <label className="campo" style={{ maxWidth: 360 }}>Sede
          <select value={sedeId} onChange={(e) => setSedeId(e.target.value)}>
            {sedes.map((s) => <option key={s.id} value={s.id}>{s.nombre}{s.activa === false ? ' (inactiva)' : ''}</option>)}
          </select>
        </label>
      </div>
      {sedeId && (
        <div key={sedeId}>
          <ConfigAprobacionFlujo sedeId={sedeId} />
          <ConfigSharePoint sedeId={sedeId} />
        </div>
      )}
    </>
  )
}
