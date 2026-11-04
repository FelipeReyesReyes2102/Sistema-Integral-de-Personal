import { useEffect, useState } from 'react'
import { Building2, KeyRound, MapPin, MessageSquareMore, Share2, ShieldCheck } from 'lucide-react'
import { api, sedeActiva } from '../api'
import ConfigAprobacionFlujo from '../components/ConfigAprobacionFlujo'
import ConfigMicrosoft from '../components/ConfigMicrosoft'
import ConfigSedes from '../components/ConfigSedes'
import ConfigSharePoint from '../components/ConfigSharePoint'

// Menú superior: sólo se muestra la sección elegida. Las dos últimas se configuran por sede.
const SECCIONES = [
  ['sedes', 'Sedes', Building2],
  ['microsoft', 'Conexión con Microsoft', KeyRound],
  ['teams', 'Aprobación en Teams', MessageSquareMore],
  ['sharepoint', 'Listas de SharePoint', Share2],
]

/** Configuración que solo puede cambiar el super administrador: global y las integraciones de cada sede. */
export default function SuperAdmin() {
  const [seccion, setSeccion] = useState('sedes')
  const [sedes, setSedes] = useState([])
  const [sedeId, setSedeId] = useState('')
  useEffect(() => {
    api('/sedes').then((l) => {
      setSedes(l)
      const activa = sedeActiva()
      setSedeId(String(l.some((s) => String(s.id) === activa) ? activa : l[0]?.id || ''))
    }).catch(() => {})
  }, [])
  const porSede = seccion === 'teams' || seccion === 'sharepoint'

  return (
    <>
      <div className="alerta warn" style={{ marginTop: 0, display: 'flex', gap: 8, alignItems: 'center' }}>
        <ShieldCheck size={16} /> Solo un super administrador puede cambiar esta configuración. La de cada sede que maneja
        su GH (política, tabla de antigüedad, correo y caseta) está en Configuración.
      </div>
      <div className="pestanas" role="tablist">
        {SECCIONES.map(([k, t, Icono]) => (
          <button key={k} role="tab" aria-selected={seccion === k} className={seccion === k ? 'activo' : ''} onClick={() => setSeccion(k)}>
            <Icono size={16} /> {t}
          </button>
        ))}
      </div>
      <div className="config-seccion" role="tabpanel">
        {seccion === 'sedes' && <ConfigSedes />}
        {seccion === 'microsoft' && <ConfigMicrosoft />}
        {porSede && (
          <div className="card sa-sede">
            <h3 className="fila" style={{ gap: 8, margin: 0 }}><MapPin size={18} /> Sede a configurar</h3>
            <p className="muted" style={{ margin: '4px 0 10px', fontSize: 13 }}>
              Cada sede tiene su propia aprobación en Teams y sus listas de SharePoint. Elige la sede que vas a configurar.
            </p>
            <label className="campo" style={{ maxWidth: 360 }}>Sede
              <select value={sedeId} onChange={(e) => setSedeId(e.target.value)}>
                {sedes.map((s) => <option key={s.id} value={s.id}>{s.nombre}{s.activa === false ? ' (inactiva)' : ''}</option>)}
              </select>
            </label>
          </div>
        )}
        {porSede && sedeId && (
          <div key={sedeId}>
            {seccion === 'teams' ? <ConfigAprobacionFlujo sedeId={sedeId} /> : <ConfigSharePoint sedeId={sedeId} />}
          </div>
        )}
      </div>
    </>
  )
}
