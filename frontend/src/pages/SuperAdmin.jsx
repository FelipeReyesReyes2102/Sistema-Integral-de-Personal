import { ShieldCheck } from 'lucide-react'
import ConfigCorreoServidor from '../components/ConfigCorreoServidor'
import ConfigMicrosoft from '../components/ConfigMicrosoft'
import ConfigSedes from '../components/ConfigSedes'

/** Configuración global que solo puede cambiar el super administrador (afecta a todas las sedes). */
export default function SuperAdmin() {
  return (
    <>
      <div className="alerta warn" style={{ marginTop: 0, display: 'flex', gap: 8, alignItems: 'center' }}>
        <ShieldCheck size={16} /> Esta configuración es común a <b>todas las sedes</b> y solo la puede cambiar un super administrador.
        La configuración de cada sede (política, tabla de antigüedad, caseta, SharePoint y aprobación en Teams) está en Configuración.
      </div>
      <ConfigSedes />
      <ConfigCorreoServidor />
      <ConfigMicrosoft />
    </>
  )
}
